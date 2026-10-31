"""Vipi engine: local speech translation for Sheng / Swahili / English (runs beside the Django backend).

    Riba   speech -> text (Whisper, in-process)
    Mufti  Swahili <-> English (MarianMT via CTranslate2, in-process, ~30-40 ms)
    Risto  anything with Sheng (fine-tuned Gemma, served by llama.cpp llama-server)
    Gemini last-resort fallback for text translation

Endpoints
    POST /v1/speech     multipart: audio (WAV), direction (to_en|to_sw), glossary (JSON [{term, meaning}])
                        -> {transcript, language, swahili, english, notes, sheng_terms, engine}; same shape
                        as the app's Gemini result, so Django can return it unchanged
    POST /v1/translate  JSON text translation (source auto|sheng|sw|en -> target sheng|sw|en)
    GET  /v1/lookup     dictionary lookup;  GET /health

Run:  cd engine && uvicorn app:app --host 127.0.0.1 --port 8100
Environment: see engine/README.md (RIBA_MODEL, RISTO_URL, MUFTI_*_DIR, GEMINI_API_KEY, VIPI_ENGINE_KEYS ...).
"""
import asyncio
import json
import os
import re
import sys
import time
from collections import OrderedDict

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vipi import prompting  # noqa: E402
from vipi.langid import detect  # noqa: E402
from vipi.lexicon import Lexicon  # noqa: E402
from vipi.normalize import clean_text, speech_form  # noqa: E402

API_KEYS = {k.strip() for k in os.environ.get("VIPI_ENGINE_KEYS", "").split(",") if k.strip()}
RISTO_URL = os.environ.get("RISTO_URL", "").rstrip("/")
RISTO_MODEL = os.environ.get("RISTO_MODEL", "risto")
RISTO_TIMEOUT_S = float(os.environ.get("RISTO_TIMEOUT_S", "8"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_TIMEOUT_S = float(os.environ.get("GEMINI_TIMEOUT_S", "15"))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
LEXICON_PATH = os.environ.get("VIPI_LEXICON", os.path.join(HERE, "data", "lexicon.sqlite"))
CACHE_SIZE = 4096
VIPI_TO_EN_RISTO_FIRST = os.environ.get("VIPI_TO_EN_RISTO_FIRST", "1") != "0"

app = FastAPI(title="Vipi engine", version="1.0")
lexicon = Lexicon.from_sqlite(LEXICON_PATH)
client = httpx.AsyncClient()
cache = OrderedDict()

mufti = {}
for pair, env in ((("sw", "en"), "MUFTI_SW_EN_DIR"), (("en", "sw"), "MUFTI_EN_SW_DIR")):
    if os.environ.get(env):
        from mufti import MuftiEngine
        threads = int(os.environ["MUFTI_THREADS"]) if os.environ.get("MUFTI_THREADS") else None
        mufti[pair] = MuftiEngine(os.environ[env], threads)

riba = None      # Kenyan side (Swahili / Sheng speech), used for to_en
riba_en = None   # tourist side (English speech), used for to_sw; falls back to riba
if os.environ.get("RIBA_MODEL"):
    from riba import RibaEngine
    riba = RibaEngine(os.environ["RIBA_MODEL"], adapter=os.environ.get("RIBA_ADAPTER") or None)
    # Swahili-specialised Whisper fine-tunes (e.g. Rogendo's helpline model) can lose English entirely,
    # so the English side can use its own model. With a Riba adapter on a shared base, the same engine serves
    # both sides (adapter off for English).
    en_model = os.environ.get("RIBA_EN_MODEL", "")
    riba_en = RibaEngine(en_model) if en_model and en_model != os.environ["RIBA_MODEL"] else riba


def require_key(x_api_key: str | None = Header(default=None)):
    if API_KEYS and x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


# ---------------------------------------------------------------- translation providers

def mufti_pair(src, tgt):
    """Mufti handles Swahili<->English; Sheng is Swahili-based, so Mufti is a rough fallback for it too."""
    pair = ("sw" if src == "sheng" else src, "sw" if tgt == "sheng" else tgt)
    return pair if pair in mufti and pair[0] != pair[1] else None


async def call_mufti(text, src, tgt, messages):
    # CTranslate2 releases the GIL, so a worker thread keeps the event loop responsive.
    return await asyncio.to_thread(mufti[mufti_pair(src, tgt)].translate, text)


async def call_risto(text, src, tgt, messages):
    resp = await client.post(f"{RISTO_URL}/chat/completions", timeout=RISTO_TIMEOUT_S, json={
        "model": RISTO_MODEL, "messages": messages, "temperature": 0, "max_tokens": 160, "stream": False})
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def call_gemini(text, src, tgt, messages):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    body = {
        "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
        "contents": [{"role": "user", "parts": [{"text": messages[1]["content"]}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512, "thinkingConfig": {"thinkingLevel": "low"}},
    }
    for _ in range(2):
        resp = await client.post(GEMINI_URL.format(GEMINI_MODEL), json=body, timeout=GEMINI_TIMEOUT_S,
                                 headers={"x-goog-api-key": GEMINI_API_KEY})
        if resp.status_code != 503:  # "high demand" spikes are short; one quick retry is worth it
            break
        await asyncio.sleep(0.5)
    if resp.status_code != 200:
        raise RuntimeError(f"gemini {resp.status_code}: {resp.text[:200]}")
    parts = resp.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


PROVIDERS = {"mufti": call_mufti, "risto": call_risto, "gemini": call_gemini}


def chain(src, tgt, forced="auto"):
    """Providers to try, in order: Swahili<->English goes to Mufti first, anything with Sheng to Risto.
    forced="risto-first" keeps Mufti as a fallback but lets Risto try first (spoken Kenyan Swahili)."""
    available = {"mufti": mufti_pair(src, tgt) is not None, "risto": bool(RISTO_URL), "gemini": bool(GEMINI_API_KEY)}
    # Sheng: Risto, then Mufti as a fast rough fallback (better than waiting on a slow/limited Gemini).
    order = ["mufti", "risto", "gemini"] if (src, tgt) in mufti else ["risto", "mufti", "gemini"]
    if forced == "risto-first":
        order = ["risto", "mufti", "gemini"]
    elif forced != "auto":
        order = [forced]
    return [p for p in order if available[p]] or order[:1]


def problem_with(output, text, src, tgt):
    """Why a model output shouldn't be trusted, or None if it looks like a real translation."""
    words, src_words = output.split(), text.split()
    if not words:
        return "empty output"
    if re.search(r"Hints:|->|<start_of_turn>|<end_of_turn>|<\|turn>|<\|channel>|<\|think\|>", output):
        return "prompt leaked into output"
    if src != tgt and len(src_words) > 3 and output.strip().lower() == text.strip().lower():
        return "output copied the input"
    if len(src_words) >= 3 and not 0.25 <= len(words) / len(src_words) <= 4:
        return "implausible length"
    trigrams = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
    if trigrams and max(trigrams.count(t) for t in set(trigrams)) >= 3:
        return "repetition loop"
    return None


def tidy(output):
    # Cut at Gemma's end-of-turn marker (Gemma 3 / Gemma 4) in case a server isn't configured to stop on it.
    for marker in ("<end_of_turn>", "<turn|>"):
        output = output.split(marker)[0]
    output = output.strip().split("\n")[0].strip()
    return output.strip('"').strip()


def glossary_hints(text, glossary):
    """User-verified terms from the app that occur in the text, as 'term = meaning' hints."""
    lower = f" {text.lower()} "
    return [f"{g['term']} = {g['meaning']}" for g in glossary
            if g.get("term") and g.get("meaning") and f" {g['term'].lower()} " in lower]


MAX_CHUNK_WORDS = 25  # Risto was trained on live segments (p95 ~17 words); long input makes it loop


def chunks(text, limit=MAX_CHUNK_WORDS):
    """Split long text at sentence/clause punctuation into pieces of at most ~limit words."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", text) if s.strip()]
    pieces = []
    for sentence in sentences:
        words = sentence.split()
        while len(words) > limit:  # no punctuation to split on: cut at a comma if possible, else hard cut
            head = " ".join(words[:limit])
            cut = head.rfind(",")
            n = len(head[:cut].split()) if cut > 0 and len(head[:cut].split()) >= limit // 2 else limit
            pieces.append(" ".join(words[:n]))
            words = words[n:]
        if words:
            pieces.append(" ".join(words))
    out = []
    for piece in pieces:  # re-merge short neighbours so each request has some context
        if out and len(out[-1].split()) + len(piece.split()) <= limit:
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out or [text]


async def translate_text(text, src, tgt, output="speech", forced="auto", glossary=()):
    """Core translation used by both endpoints. Long text is translated chunk by chunk, in parallel."""
    parts = chunks(text)
    if len(parts) == 1:
        return await translate_piece(text, src, tgt, output, forced, glossary)
    results = await asyncio.gather(*(translate_piece(p, src, tgt, output, forced, glossary) for p in parts))
    providers = list(dict.fromkeys(r["provider"] for r in results))
    failures = [r["fallback_reason"] for r in results if r.get("fallback_reason")]
    return {"translation": " ".join(r["translation"] for r in results), "provider": "+".join(providers),
            "fallback_reason": "; ".join(failures) or None,
            "hints": list(dict.fromkeys(h for r in results for h in r["hints"])), "chunks": len(parts)}


async def translate_piece(text, src, tgt, output="speech", forced="auto", glossary=()):
    """One segment through the provider chain. Returns a dict with translation, provider, failures, hints."""
    if src == tgt:
        return {"translation": speech_form(text, tgt) if output == "speech" else text, "provider": "passthrough",
                "fallback_reason": None, "hints": []}
    key = (text.lower(), src, tgt, output, forced, json.dumps(list(glossary), sort_keys=True))
    if key in cache:
        cache.move_to_end(key)
        return {**cache[key], "cached": True}
    hints = list(dict.fromkeys(glossary_hints(text, glossary) + lexicon.hints(text, src, tgt)))[:8]
    messages = prompting.messages(text, src, tgt, hints)
    result, failures = None, []
    for name in chain(src, tgt, forced):
        try:
            candidate = tidy(await PROVIDERS[name](text, src, tgt, messages))
            problem = problem_with(candidate, text, src, tgt)
            if problem is None:
                result = (candidate, name)
                break
            failures.append(f"{name}: {problem}")
        except httpx.TimeoutException:
            failures.append(f"{name}: timed out")
        except Exception as exc:  # connection refused, 5xx, quota, bad JSON...
            failures.append(f"{name}: {type(exc).__name__}: {str(exc)[:200]}")
    if result is None:
        raise HTTPException(status_code=502, detail="all providers failed; " + "; ".join(failures))
    translation, provider = result
    if output == "speech":
        translation = speech_form(translation, tgt)
    out = {"translation": translation, "provider": provider, "fallback_reason": "; ".join(failures) or None,
           "hints": hints if provider != "mufti" else []}
    cache[key] = out
    if len(cache) > CACHE_SIZE:
        cache.popitem(last=False)
    return out


def sheng_terms(text, glossary):
    """Sheng words in the transcript with their meanings (the app shows these as learnable terms)."""
    found, seen = [], set()
    for g in glossary:
        if g.get("term") and f" {g['term'].lower()} " in f" {text.lower()} ":
            found.append({"term": g["term"], "meaning": g.get("meaning", "")})
            seen.add(g["term"].lower())
    for word in re.findall(r"[a-zA-Z']{3,}", text):
        w = word.lower()
        if w in lexicon.sheng and w not in lexicon.sw and w not in seen:
            seen.add(w)
            found.append({"term": word, "meaning": "; ".join(lexicon.sheng[w]["en"][:2])})
    return found[:10]


# ---------------------------------------------------------------- endpoints

class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    source: str = Field("auto", pattern="^(auto|sheng|sw|en)$")
    target: str = Field(..., pattern="^(sheng|sw|en)$")
    output: str = Field("speech", pattern="^(speech|text)$", description="speech = TTS-ready (numbers etc. spelled out)")
    provider: str = Field("auto", pattern="^(auto|mufti|risto|gemini)$", description="force one provider (testing)")


@app.post("/v1/translate", dependencies=[Depends(require_key)])
async def translate(req: TranslateRequest):
    start = time.perf_counter()
    text = clean_text(req.text)
    src = detect(text, lexicon) if req.source == "auto" else req.source
    out = await translate_text(text, src, req.target, req.output, req.provider)
    return {**out, "source": src, "target": req.target, "latency_ms": round(1000 * (time.perf_counter() - start))}


@app.post("/v1/speech", dependencies=[Depends(require_key)])
async def speech(audio: UploadFile = File(...), direction: str = Form("to_en"), glossary: str = Form("[]")):
    """Riba transcribes, then Mufti / Risto translate. to_en: a Kenyan speaking Sheng/Swahili/English to a
    tourist; to_sw: a tourist speaking English. Response matches the app's live-translation result."""
    if direction not in ("to_en", "to_sw"):
        raise HTTPException(status_code=400, detail="direction must be to_en or to_sw")
    if riba is None:
        raise HTTPException(status_code=503, detail="Riba (speech recognition) is not configured")
    try:
        terms = [g for g in json.loads(glossary or "[]") if isinstance(g, dict)][:300]
    except ValueError:
        terms = []

    started = time.perf_counter()
    data = await audio.read()
    asr = riba if direction == "to_en" else riba_en
    transcript = await asyncio.to_thread(asr.transcribe, data, "sw" if direction == "to_en" else "en")
    asr_ms = round(1000 * (time.perf_counter() - started))
    engine = {"asr": asr.name + (f"+{asr.adapter}" if asr.adapter and direction == "to_en" else ""),
              "asr_ms": asr_ms, "providers": {}}
    if not transcript:
        return {"transcript": "", "language": "silence", "swahili": "", "english": "", "notes": "",
                "sheng_terms": [], "engine": engine}

    text = clean_text(transcript)
    if direction == "to_sw":
        src = "en"
    else:
        src = detect(text, lexicon)
        # Any Sheng-only word means Mufti (standard Swahili) could mangle the slang, so let Risto take it.
        if src == "sw" and sheng_terms(text, terms):
            src = "sheng"
    language = {"sheng": "sheng", "sw": "swahili", "en": "english"}[src]

    t0 = time.perf_counter()
    targets = [t for t in ("en", "sw") if t != src]
    # Spoken Kenyan Swahili is rarely free of Sheng, and speech recognition can garble slang so it isn't
    # detected; Risto copes with both (and is as good as Mufti on plain Swahili->English), so it goes first
    # there. English->Swahili stays Mufti-first, where Mufti is clearly best.
    prefer = "risto-first" if direction == "to_en" and src == "sw" and VIPI_TO_EN_RISTO_FIRST else "auto"
    results = await asyncio.gather(*(translate_text(text, src, t, forced=prefer if t == "en" else "auto",
                                                    glossary=terms) for t in targets))
    out = dict(zip(targets, results))
    engine["translate_ms"] = round(1000 * (time.perf_counter() - t0))
    engine["providers"] = {t: r["provider"] for t, r in out.items()}
    fallbacks = {t: r["fallback_reason"] for t, r in out.items() if r.get("fallback_reason")}
    if fallbacks:
        engine["fallbacks"] = fallbacks
    return {
        "transcript": transcript,
        "language": language,
        "english": out["en"]["translation"] if "en" in out else speech_form(text, "en"),
        "swahili": out["sw"]["translation"] if "sw" in out else speech_form(text, "sw"),
        "notes": "",
        "sheng_terms": sheng_terms(text, terms) if src == "sheng" else [],
        "engine": engine,
    }


@app.get("/v1/lookup", dependencies=[Depends(require_key)])
async def lookup(q: str):
    word = q.strip().lower()
    entries = [e for table in (lexicon.sheng, lexicon.sw) for form, e in table.items() if form == word]
    return {"query": q, "entries": [{k: e.get(k) for k in ("term", "lang", "pos", "en", "sw", "examples", "synonyms")}
                                    for e in entries]}


@app.get("/health")
async def health():
    risto = "not configured"
    if RISTO_URL:
        try:
            r = await client.get(f"{RISTO_URL.removesuffix('/v1')}/health", timeout=2)
            risto = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception as exc:
            risto = f"down ({type(exc).__name__})"
    return {"status": "ok", "riba": (f"{riba.name}+{riba.adapter}" if riba and riba.adapter else
                                      riba.name if riba else "not configured") + (f" on {riba.device}" if riba else ""),
            "riba_en": f"{riba_en.name} on {riba_en.device}" if riba_en else "not configured", "risto": risto,
            "mufti": [f"{s}->{t}" for s, t in mufti] or "not configured",
            "gemini": "configured" if GEMINI_API_KEY else "not configured",
            "lexicon_entries": len(lexicon.sheng) + len(lexicon.sw)}

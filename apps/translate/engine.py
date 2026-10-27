"""Sauti Engine v0: Gemini audio → structured translation (same prompts as the app)."""
import base64
import json
import logging
import time

import requests
from django.conf import settings

log = logging.getLogger("vipi")

PERSONA = (
    "You are Vipi!, an expert Kenyan interpreter fluent in Kenyan Swahili, Sheng (Nairobi urban slang "
    "mixing Swahili, English and other Kenyan languages) and English. You know matatu, market, boda boda, "
    "hotel and safari talk, and Kenyan politeness (greetings, \"mzee\", \"pole\", \"sasa\")."
)

TASKS = {
    "to_en": (
        "The audio is a Kenyan speaking to a tourist, in Sheng, Swahili, English or a mix. Fill: transcript = "
        "exactly what was said (keep Sheng spelling); swahili = the same in clear standard Swahili; english = "
        "a natural, short English translation for the tourist (translate meaning and slang, not word-for-word); "
        "notes = at most one short sentence of cultural or slang context, or \"\" if none; sheng_terms = Sheng "
        "words used and their meaning."
    ),
    "to_sw": (
        "The audio is a tourist speaking English (maybe with a few Swahili words) to a Kenyan. Fill: transcript "
        "= exactly what was said; swahili = a natural, friendly Kenyan Swahili translation a local would "
        "understand (simple everyday Swahili, not formal); english = cleaned-up English of what was said; "
        "notes = a short tip on politeness or pronunciation, or \"\"; sheng_terms = []."
    ),
}

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {"type": "STRING"},
        "language": {"type": "STRING", "enum": ["sheng", "swahili", "english", "mixed", "silence"]},
        "swahili": {"type": "STRING"},
        "english": {"type": "STRING"},
        "notes": {"type": "STRING"},
        "sheng_terms": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"term": {"type": "STRING"}, "meaning": {"type": "STRING"}},
                "required": ["term", "meaning"],
            },
        },
    },
    "required": ["transcript", "language", "swahili", "english", "notes"],
}


class EngineError(Exception):
    pass


def wav_seconds(data: bytes) -> float:
    """Duration of a 16-bit PCM WAV from its header (falls back to 16 kHz mono)."""
    try:
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            channels = int.from_bytes(data[22:24], "little") or 1
            rate = int.from_bytes(data[24:28], "little") or 16000
            bits = int.from_bytes(data[34:36], "little") or 16
            return max(0.0, (len(data) - 44) / (rate * channels * bits / 8))
    except Exception:  # noqa: BLE001
        pass
    return max(0.0, (len(data) - 44) / 32000)


def build_prompt(direction: str, glossary: list[dict] | None) -> str:
    gl = ""
    if glossary:
        lines = "\n".join(f"- {t.get('term','')}: {t.get('meaning','')}" for t in glossary[:300] if t.get("term"))
        if lines:
            gl = f"\nTerms the user has verified (trust these over your own guess):\n{lines}\n"
    return (f"{PERSONA}\n{gl}\n{TASKS[direction]}\nIf the audio is silent or unclear, set language to "
            f"\"silence\" and leave the other fields empty.")


def translate_clip(audio: bytes, direction: str, glossary=None, mime="audio/wav") -> tuple[dict, int, str]:
    """Returns (result_json, latency_ms, model)."""
    key = settings.GEMINI_API_KEY
    model = settings.GEMINI_MODEL
    if not key:
        raise EngineError("Server has no GEMINI_API_KEY configured.")
    config = {"temperature": 0.2, "responseMimeType": "application/json", "responseSchema": SCHEMA}
    if "2.5-flash" in model:
        config["thinkingConfig"] = {"thinkingBudget": 0}
    elif model.startswith("gemini-3"):
        # 3.x can't switch thinking off ("minimal" is gone); "low" is the fastest.
        config["thinkingConfig"] = {"thinkingLevel": "low"}
    body = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
            {"text": build_prompt(direction, glossary)},
        ]}],
        "generationConfig": config,
    }
    started = time.monotonic()
    try:
        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            data=json.dumps(body), timeout=45,
        )
    except requests.RequestException as e:
        raise EngineError(f"Engine unreachable: {e}") from e
    latency = int((time.monotonic() - started) * 1000)
    if res.status_code != 200:
        try:
            msg = res.json()["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = res.text[:200]
        raise EngineError(f"Gemini {res.status_code}: {msg}")
    data = res.json()
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        out = json.loads(text)
    except Exception as e:  # noqa: BLE001
        raise EngineError("Could not read the engine's answer.") from e
    out.setdefault("sheng_terms", [])
    return out, latency, model

"""Machine suggestions for a clip's meaning, from the Vipi engine, so contributors correct instead of typing.

English: Risto (Sheng → English) first, Mufti's reading as standard Swahili → English as the alternative.
Swahili: Risto (Sheng → standard Swahili) and Mufti on Risto's English; when Risto mostly copies the Sheng back,
Mufti's comes first.
Providers are always forced, so a failed suggestion never falls back to Gemini (its free tier is 20 requests a day).
"""
import logging

import requests
from django.conf import settings

log = logging.getLogger("vipi")


def _translate(text, source, target, provider):
    try:
        res = requests.post(f"{settings.VIPI_ENGINE_URL.rstrip('/')}/v1/translate",
                            json={"text": text, "source": source, "target": target, "provider": provider,
                                  "output": "text"},
                            headers={"X-API-Key": settings.VIPI_ENGINE_KEY} if settings.VIPI_ENGINE_KEY else {},
                            timeout=settings.VIPI_ENGINE_TIMEOUT)
        if res.status_code == 200:
            out = " ".join(res.json().get("translation", "").split())
            # an "answer" that is the input again is no suggestion at all
            return out if out and out.lower() != " ".join(text.split()).lower() else None
    except requests.RequestException as e:
        log.warning("meaning draft: engine unreachable: %s", e)
    return None


def overlap(a, b):
    """Share of a's words that also occur in b (1.0 = a is b copied)."""
    words = [w.strip(".,?!").lower() for w in a.split()]
    other = {w.strip(".,?!").lower() for w in b.split()}
    return sum(w in other for w in words) / len(words) if words else 1.0


def meaning_drafts(text):
    """{"en": [{"by", "text"}…], "sw": […]}, best suggestion first, duplicates dropped."""
    if not settings.VIPI_ENGINE_URL or not text:
        return {}
    en = [("risto", _translate(text, "sheng", "en", "risto")), ("mufti", _translate(text, "sw", "en", "mufti"))]
    sw = [("risto", _translate(text, "sheng", "sw", "risto"))]
    first_en = next((t for _, t in en if t), None)
    if first_en:
        sw.append(("mufti", _translate(first_en, "en", "sw", "mufti")))
    out = {}
    for lang, candidates in (("en", en), ("sw", sw)):
        seen, keep = set(), []
        for by, t in candidates:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                keep.append({"by": by, "text": t})
        # Risto often hands the Sheng back with a few words changed: rank by how little of the transcript it repeats
        out[lang] = sorted(keep, key=lambda o: overlap(o["text"], text) > 0.5)
    return out


def fill(clip):
    """Store suggestions for the clip's current transcript (redone if the transcript was fixed since)."""
    if clip.meaning_drafts.get("for") == clip.text:
        return
    drafts = meaning_drafts(clip.text)
    if drafts.get("en") or drafts.get("sw"):
        clip.meaning_drafts = {**drafts, "for": clip.text}
        type(clip).objects.filter(pk=clip.pk).update(meaning_drafts=clip.meaning_drafts)

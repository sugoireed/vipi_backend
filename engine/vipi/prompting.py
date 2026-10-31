"""The one prompt format shared by training data, the local model and the Gemini fallback.

Kept deliberately short: on a live device every prompt token costs latency.
"""
LANG_NAMES = {"sheng": "Sheng", "sw": "Swahili", "en": "English"}
LANGS = tuple(LANG_NAMES)

SYSTEM = ("You are Vipi, a live speech translator for Sheng, Swahili and English. "
          "Reply with only the translation, written the way it should be spoken.")


def user_prompt(text, src, tgt, hints=()):
    lines = [f"{LANG_NAMES[src]} -> {LANG_NAMES[tgt]}"]
    if hints:
        lines.append("Hints: " + "; ".join(hints))
    lines.append(text)
    return "\n".join(lines)


def messages(text, src, tgt, hints=(), answer=None):
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(text, src, tgt, hints)}]
    if answer is not None:
        msgs.append({"role": "assistant", "content": answer})
    return msgs

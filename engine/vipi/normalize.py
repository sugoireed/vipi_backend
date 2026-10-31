"""Text normalization for a speech-to-speech translator (ASR -> MT -> TTS).

clean_text   general cleanup used everywhere (unicode, HTML leftovers, URLs, quotes, whitespace)
asr_form     what a speech recognizer emits: lowercase, no punctuation, numbers as words
speech_form  what a TTS engine should receive: numbers, currency, percentages, times and symbols written
             out as words, emojis/URLs removed, sentence punctuation kept for prosody

Numbers are verbalized in Swahili for "sw" and "sheng" and in English for "en".
"""
import html
import re
import unicodedata

SW_UNITS = ["sifuri", "moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane", "tisa"]
SW_TENS = ["", "kumi", "ishirini", "thelathini", "arobaini", "hamsini", "sitini", "sabini", "themanini", "tisini"]
EN_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
            "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

URL = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+\.\w+)")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D]")
TAGS = re.compile(r"<[^>]+>")
QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "`": "'", "–": "-", "—": "-", "…": "...", " ": " "})


def _lang(lang):
    return "en" if lang == "en" else "sw"


# ---------------------------------------------------------------- numbers

def sw_number(n):
    if n < 10:
        return SW_UNITS[n]
    parts = []
    for size, name in ((10 ** 9, "bilioni"), (10 ** 6, "milioni"), (1000, "elfu")):
        if n >= size:
            parts.append(f"{name} {sw_number(n // size)}")
            n %= size
    if n >= 100:
        parts.append(f"mia {SW_UNITS[n // 100]}" if n // 100 < 10 else f"mia {sw_number(n // 100)}")
        n %= 100
    if n >= 10:
        parts.append(SW_TENS[n // 10])
        n %= 10
    if n:
        parts.append(SW_UNITS[n])
    return parts[0] if len(parts) == 1 else " ".join(parts[:-1]) + " na " + parts[-1]


def en_number(n):
    if n < 20:
        return EN_UNITS[n]
    if n < 100:
        return EN_TENS[n // 10] + ("-" + EN_UNITS[n % 10] if n % 10 else "")
    if n < 1000:
        return EN_UNITS[n // 100] + " hundred" + (" and " + en_number(n % 100) if n % 100 else "")
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            rest = n % size
            return en_number(n // size) + f" {name}" + ((" and " if rest < 100 else " ") + en_number(rest) if rest else "")
    return str(n)


def number_words(n, lang):
    return en_number(n) if _lang(lang) == "en" else sw_number(n)


def _digits(s, lang):
    units = EN_UNITS if _lang(lang) == "en" else SW_UNITS
    return " ".join(units[int(d)] for d in s)


def _decimal(s, lang):
    whole, _, frac = s.partition(".")
    point = "point" if _lang(lang) == "en" else "nukta"
    return f"{number_words(int(whole), lang)} {point} {_digits(frac, lang)}"


def _time(h, m, lang):
    h, m = int(h), int(m)
    if _lang(lang) == "en":
        return en_number(h) + ("" if m == 0 else " oh " + en_number(m) if m < 10 else " " + en_number(m))
    # Swahili time counts hours from 6 am/pm: 7:00 is "saa moja".
    hour = sw_number((h + 6) % 12 or 12)
    tail = {0: "", 15: " na robo", 30: " na nusu"}.get(m, f" na dakika {sw_number(m)}")
    return f"saa {hour}{tail}"


CURRENCY = re.compile(r"\b(?:ksh|kshs|kes|sh|shs)\.?\s?(\d[\d,]*(?:\.\d+)?)\b|\b(\d[\d,]*)\s?(?:ksh|kshs|kes|bob)\b", re.I)
_AMOUNT_WORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\w+teen|\w+ty(?:-\w+)?|hundred|"
                r"thousand|million|billion|and|sifuri|moja|mbili|tatu|nne|tano|sita|saba|nane|tisa|kumi|ishirini|"
                r"thelathini|arobaini|hamsini|sitini|sabini|themanini|tisini|mia|elfu|laki|milioni|bilioni|na)")
CURRENCY_WORD = re.compile(rf"\b(?:ksh|kshs|kes)\.?\s+((?:{_AMOUNT_WORD}\b[\s-]*)+)", re.I)
DOLLAR = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
TIME = re.compile(r"\b(?:saa\s+)?([01]?\d|2[0-3]):([0-5]\d)\b", re.I)  # "saa 10:30" must not become "saa saa ..."
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _num(s, lang):
    s = s.replace(",", "")
    if "." in s:
        return _decimal(s, lang)
    if len(s) >= 7 or (len(s) > 1 and s.startswith("0")):
        return _digits(s, lang)  # phone numbers, codes
    return number_words(int(s), lang)


def verbalize_numbers(text, lang):
    def money(m):
        amount = _num(m.group(1) or m.group(2), lang)
        return f"{amount} shillings" if _lang(lang) == "en" else f"shilingi {amount}"

    text = CURRENCY.sub(money, text)
    # A currency code left before an amount already in words ("Ksh eight hundred") is still unreadable for TTS.
    text = CURRENCY_WORD.sub(lambda m: (m.group(1).strip(" -") + " shillings ") if _lang(lang) == "en"
                             else ("shilingi " + m.group(1).strip(" -") + " "), text)
    text = DOLLAR.sub(lambda m: f"{_num(m.group(1), lang)} dollars" if _lang(lang) == "en" else f"dola {_num(m.group(1), lang)}", text)
    text = PERCENT.sub(lambda m: f"{_num(m.group(1), lang)} percent" if _lang(lang) == "en" else f"asilimia {_num(m.group(1), lang)}", text)
    text = TIME.sub(lambda m: _time(m.group(1), m.group(2), lang), text)
    # Glue like "26-years-old" or "Obio/Akpor" reads better spaced out.
    text = re.sub(r"(\d)-(?=[a-zA-Z])", r"\1 ", text)
    return NUMBER.sub(lambda m: _num(m.group(0), lang), text)


# ---------------------------------------------------------------- forms

def clean_text(text):
    text = html.unescape(TAGS.sub(" ", text or ""))
    text = unicodedata.normalize("NFC", text).translate(QUOTES)
    text = URL.sub(" ", text)
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C" or c in "\n\t")
    return " ".join(text.split())


def speech_form(text, lang):
    """Text as a TTS engine should get it: everything pronounceable, punctuation kept for prosody."""
    text = clean_text(text)
    text = EMOJI.sub(" ", text)
    text = verbalize_numbers(text, lang)
    text = text.replace("&", " and " if _lang(lang) == "en" else " na ")
    text = re.sub(r"[\"*_#@<>{}\[\]|~^=+\\]", " ", text)
    text = re.sub(r"\s*[()]\s*", ", ", text)
    text = re.sub(r"[,;:]\s*([.!?])", r"\1", text)  # ", ." left by removed brackets -> "."
    text = re.sub(r"\s*([,.!?;:])(\s*[,;:])+", r"\1", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return " ".join(text.split()).strip(" ,;:-")


def asr_form(text, lang):
    """Text as a speech recognizer typically emits it: lowercase words, no punctuation, numbers spoken."""
    text = speech_form(text, lang).lower()
    text = re.sub(r"[^\w\s']", " ", text)
    return " ".join(text.split())

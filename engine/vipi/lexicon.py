"""In-memory Sheng/Swahili lexicon used to give the translator short dictionary hints.

Loaded from data/final/lexicon.jsonl (or lexicon.sqlite on the server). Hints are kept short because every
token in the prompt adds latency on a live device.
"""
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict

WORD = re.compile(r"[a-zA-Z']+")
HINT_POS = {"noun", "adjective", "adverb", "interjection", "pronoun", "adj", "adv", "intj", "pron", "phrase"}
MAX_HINTS = 6


def _single_meaning(text):
    """'Money' / 'A thousand shilling (note)' -> 'money' / '' (only one-word meanings are safe to reverse)."""
    text = re.sub(r"\(.*?\)", "", text).strip().lower()
    text = re.sub(r"^(a|an|the|to)\s+", "", text)
    return text if re.fullmatch(r"[a-z]+", text) else ""


class Lexicon:
    def __init__(self, entries, bridge=None):
        """bridge: optional validated {swahili word: [sheng terms]} (see validate_bridge); replaces the raw
        English-meaning bridge, which is noisy for homographs like "nina" (I have / mother)."""
        self.sheng = {}                      # sheng form -> entry
        self.sw = {}                         # swahili form -> entry
        self.en_to_sheng = defaultdict(list)  # english word -> sheng terms
        for e in entries:
            forms = [e["term"]] + e.get("variants", [])
            table = self.sheng if e["lang"] == "sheng" else self.sw
            for form in forms:
                form = form.strip().lower()
                if len(form) > 2:
                    table.setdefault(form, e)
        for e in entries:
            if e["lang"] == "sheng" and e["pos"].lower() in HINT_POS | {"verb"}:
                for meaning in e["en"]:
                    word = _single_meaning(meaning)
                    if word and e["term"] not in self.en_to_sheng[word]:
                        self.en_to_sheng[word].append(e["term"])
        # Swahili -> Sheng: Gemini's Swahili equivalents first, then a bridge through shared one-word English meanings.
        self.sw_to_sheng = defaultdict(list)
        for e in entries:
            if e["lang"] == "sheng":
                for sw in e.get("sw", []):
                    if " " not in sw.strip():
                        self.sw_to_sheng[sw.strip().lower()].append(e["term"])
        self.bridge_candidates = {}  # swahili word -> (english word, sheng terms)
        for form, e in self.sw.items():
            if e["pos"].lower() in HINT_POS and form not in self.sw_to_sheng:
                for gloss in e["en"][:2]:
                    word = _single_meaning(gloss)
                    if word in self.en_to_sheng:
                        self.bridge_candidates[form] = (word, self.en_to_sheng[word][:3])
                        break
        for form, (_, sheng) in self.bridge_candidates.items():
            if bridge is None or form in bridge:
                self.sw_to_sheng.setdefault(form, sheng)

    def validate_bridge(self, en_sw_pairs, min_ratio=0.4, min_seen=3):
        """Keep a Swahili->English->Sheng bridge only if, in real parallel sentences, Swahili sentences with the
        word usually have the English word on the other side. Unseen/rare words are dropped (can't verify)."""
        seen, hit = Counter(), Counter()
        for en, sw in en_sw_pairs:
            en_words = set(WORD.findall(en.lower()))
            for w in set(WORD.findall(sw.lower())):
                if w in self.bridge_candidates:
                    seen[w] += 1
                    hit[w] += self.bridge_candidates[w][0] in en_words
        return {w: sheng for w, (_, sheng) in self.bridge_candidates.items()
                if seen[w] >= min_seen and hit[w] / seen[w] >= min_ratio}

    @staticmethod
    def _bridge_for(path):
        p = os.path.join(os.path.dirname(path), "sw_sheng_bridge.json")
        return json.load(open(p)) if os.path.exists(p) else None

    @classmethod
    def from_jsonl(cls, path):
        return cls([json.loads(line) for line in open(path)], cls._bridge_for(path))

    @classmethod
    def from_sqlite(cls, path):
        db = sqlite3.connect(path)
        entries = [json.loads(row[0]) for row in db.execute("SELECT data FROM entries")]
        db.close()
        return cls(entries, cls._bridge_for(path))

    @classmethod
    def default(cls):
        here = os.path.join(os.path.dirname(__file__), "..", "data", "final")
        path = os.environ.get("VIPI_LEXICON", os.path.join(here, "lexicon.sqlite"))
        return cls.from_sqlite(path) if path.endswith(".sqlite") else cls.from_jsonl(path)

    def hints(self, text, src, tgt):
        """Short 'word = meaning' hints for the words in text that the lexicon knows."""
        out = []
        for word in dict.fromkeys(w.lower() for w in WORD.findall(text)):
            if src == "sheng" and word in self.sheng and word not in self.sw:
                e = self.sheng[word]
                meaning = self._meaning_for(e, tgt)
                if meaning:
                    out.append(f"{word} = {meaning}")
            elif tgt == "sheng" and src == "en" and word in self.en_to_sheng:
                out.append(f"{word} = {' / '.join(self.en_to_sheng[word][:3])}")
            elif tgt == "sheng" and src == "sw" and word in self.sw_to_sheng:
                out.append(f"{word} = {' / '.join(self.sw_to_sheng[word][:3])}")
            if len(out) >= MAX_HINTS:
                break
        return out

    @staticmethod
    def _meaning_for(e, tgt):
        if tgt == "sw" and e.get("sw"):
            return ", ".join(e["sw"][:2])
        return re.sub(r"\s+", " ", "; ".join(e["en"][:2]))[:60]

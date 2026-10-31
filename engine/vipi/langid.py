"""Tiny Sheng / Swahili / English detector for short utterances (used when the caller sends source="auto")."""
import re

WORD = re.compile(r"[a-z']+")
EN = set("the a an is are was were i you he she it we they this that what where when how why do does did not have has "
         "will would can could to of in on for with my your me him her them please thank yes no".split())
SW = set("na ya wa kwa ni za la hii hiyo huyo yule kama lakini sasa wapi nini nani lini vipi sana tu pia bado ndiyo "
         "hapana asante tafadhali mimi wewe yeye sisi nyinyi wao nataka ninaenda nina una ana tuna mna wana".split())


def detect(text, lexicon=None):
    words = WORD.findall(text.lower())
    if not words:
        return "sw"
    en = sum(w in EN for w in words)
    sw = sum(w in SW for w in words)
    sheng = sum(1 for w in words if lexicon and w in lexicon.sheng and w not in lexicon.sw and w not in EN)
    if en > sw and en >= sheng:
        return "en"
    # Sheng is Swahili-based: Swahili grammar words plus slang vocabulary.
    return "sheng" if sheng and sheng >= max(1, len(words) // 6) else "sw"

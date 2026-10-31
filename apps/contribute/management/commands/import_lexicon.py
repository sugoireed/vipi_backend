"""Loads the Sheng dictionary entries from sheng_dataset's lexicon into the word-check queue.

    python manage.py import_lexicon ../sheng_dataset/data/final/lexicon.jsonl

Only Sheng entries (sheng.co.ke) are loaded; standard Swahili ones come from Wiktionary and need no check.
Safe to rerun: new words are added, words people have already checked are never touched.
"""
import json

from django.core.management.base import BaseCommand

from apps.contribute.models import LexiconWord


class Command(BaseCommand):
    help = "Load Sheng dictionary words into the word-check queue"

    def add_arguments(self, parser):
        parser.add_argument("lexicon", help="sheng_dataset data/final/lexicon.jsonl")

    def handle(self, lexicon, **opts):
        existing = set(LexiconWord.objects.values_list("term", "pos"))
        new = []
        for line in open(lexicon):
            e = json.loads(line)
            if e["lang"] != "sheng" or (e["term"], e["pos"]) in existing:
                continue
            existing.add((e["term"], e["pos"]))
            new.append(LexiconWord(term=e["term"], pos=e["pos"], meanings_en=e["en"], examples=e["examples"],
                                   synonyms=e["synonyms"], sw=e.get("sw", [])))
        LexiconWord.objects.bulk_create(new, batch_size=500)
        self.stdout.write(f"{len(new)} new words ({len(existing) - len(new)} already loaded)")

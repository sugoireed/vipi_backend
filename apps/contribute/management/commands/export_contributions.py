"""Writes everything contributors verified back into sheng_dataset for training.

    python manage.py export_contributions ../sheng_dataset

Only work a second person approved is exported:
  data/final/riba/contributed_talk.jsonl         verified transcripts: {"audio", "text", "source", "speaker", "duration"}
                                                 (Riba; clips still containing [?] are left out)
  data/parallel/contributed_meanings.jsonl       verified meanings: {"sheng", "en", "sw", "source", translators}
                                                 (Risto parallel data)
  data/dictionary/sheng_human_review.jsonl       verified word checks: {"word", "pos", "sw", "en_ok", "en_note"}
                                                 (same shape as Gemini's enrichment; build_dataset prefers it)
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.contribute.models import LexiconWord, SpeechClip


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


class Command(BaseCommand):
    help = "Export verified transcripts, meanings and word checks to sheng_dataset"

    def add_arguments(self, parser):
        parser.add_argument("dataset", help="path to the sheng_dataset checkout")

    def handle(self, dataset, **opts):
        root, out = Path(settings.TRANSCRIPT_CLIPS_ROOT).resolve(), Path(dataset)
        verified = SpeechClip.objects.filter(transcript_status=SpeechClip.Transcript.VERIFIED).order_by("audio")
        talk = [{"audio": str(root / c.audio), "text": c.text, "source": c.source, "speaker": c.episode,
                 "duration": c.duration} for c in verified if "[?]" not in c.text]
        meanings = [{"sheng": c.text, "en": c.meaning_en, "sw": c.meaning_sw, "source": f"{c.source}_contributed",
                     "en_translator": "human", "sw_translator": "human"}
                    for c in verified.filter(meaning_status=SpeechClip.Meaning.VERIFIED) if "[?]" not in c.text]
        words = [{"word": w.term, "pos": w.pos, "sw": w.sw, "en_ok": w.en_ok, "en_note": w.en_correction}
                 for w in LexiconWord.objects.filter(status=LexiconWord.Status.VERIFIED)]
        n = (write(out / "data/final/riba/contributed_talk.jsonl", talk),
             write(out / "data/parallel/contributed_meanings.jsonl", meanings),
             write(out / "data/dictionary/sheng_human_review.jsonl", words))
        self.stdout.write(f"{n[0]} transcripts ({sum(r['duration'] for r in talk) / 60:.1f} min), "
                          f"{n[1]} meanings, {n[2]} words → {out}")

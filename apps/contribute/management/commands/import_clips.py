"""Loads talk clips (and Riba drafts when present) into the contribution queue.

    python manage.py import_clips sheng_talks_clips      # folder under TRANSCRIPT_CLIPS_ROOT
    python manage.py import_clips sheng_radio

Reads <folder>/drafts.jsonl if it exists, else <folder>/manifest.jsonl (both written by sheng_dataset). Safe to rerun:
new clips are added, drafts are filled in or replaced on clips still waiting for a transcript, and nobody's work
is touched.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.contribute.models import SpeechClip


class Command(BaseCommand):
    help = "Load talk clips + Riba drafts into the contribution queue"

    def add_arguments(self, parser):
        parser.add_argument("folder", help="clip folder, relative to TRANSCRIPT_CLIPS_ROOT")

    def handle(self, folder, **opts):
        base = Path(settings.TRANSCRIPT_CLIPS_ROOT) / folder
        manifest = base / "drafts.jsonl" if (base / "drafts.jsonl").exists() else base / "manifest.jsonl"
        if not manifest.exists():
            raise CommandError(f"no drafts.jsonl or manifest.jsonl in {base}")
        rows = [json.loads(line) for line in manifest.open()]

        existing = {c.audio: c for c in SpeechClip.objects.filter(audio__startswith=f"{folder}/")}
        new, drafted = [], []
        for r in rows:
            audio = f"{folder}/{r['audio']}"
            clip = existing.get(audio)
            if clip is None:
                new.append(SpeechClip(
                    source=r.get("source", folder), audio=audio, episode=r["audio"].split("/")[0],
                    start=str(r.get("start", "")), duration=r.get("duration", 0), speech_score=r.get("speech"),
                    music_score=r.get("music"), draft=r.get("draft", ""), draft_confidence=r.get("confidence")))
            elif (r.get("draft") and clip.transcript_status == SpeechClip.Transcript.PENDING
                  and (clip.draft, clip.draft_confidence) != (r["draft"], r.get("confidence"))):  # new or better draft
                clip.draft, clip.draft_confidence = r["draft"], r.get("confidence")
                drafted.append(clip)
        SpeechClip.objects.bulk_create(new, batch_size=500)
        SpeechClip.objects.bulk_update(drafted, ["draft", "draft_confidence"], batch_size=500)
        self.stdout.write(f"{manifest.name}: {len(new)} new clips, {len(drafted)} drafts added, "
                          f"{len(rows) - len(new) - len(drafted)} already up to date")

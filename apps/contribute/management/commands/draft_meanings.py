"""Fills Risto/Mufti meaning suggestions for every verified transcript still waiting for a meaning.

    python manage.py draft_meanings

New transcripts get theirs in the background as soon as they're verified; this catches up the rest (e.g. after
the engine was down). Needs VIPI_ENGINE_URL; never uses Gemini.
"""
from django.core.management.base import BaseCommand

from apps.contribute import drafts
from apps.contribute.models import SpeechClip


class Command(BaseCommand):
    help = "Fill machine meaning suggestions for verified transcripts"

    def handle(self, **opts):
        waiting = SpeechClip.objects.filter(transcript_status=SpeechClip.Transcript.VERIFIED,
                                            meaning_status=SpeechClip.Meaning.NONE)
        done = 0
        for clip in waiting:
            drafts.fill(clip)
            done += bool(clip.meaning_drafts.get("en") or clip.meaning_drafts.get("sw"))
        self.stdout.write(f"{done} of {waiting.count()} waiting clips have suggestions")

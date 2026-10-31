"""Data contributed by invited people: talk-clip transcripts and meanings, and Sheng dictionary checks.

Every piece of work is checked by a second person before it is exported for training (Riba: transcripts, Risto:
meanings and the lexicon). Contribution keeps the full history, which gives per-person counts and approval rates.
"""
from django.conf import settings
from django.db import models

USER = settings.AUTH_USER_MODEL


class Claimable(models.Model):
    """An item handed to one contributor at a time, so two people don't work on the same clip."""

    claimed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    claimed_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class SpeechClip(Claimable):
    """A short talk clip (Sheng radio stream, Sheng Talk episodes) with Riba's draft, transcript and meaning.

    The audio stays on disk under TRANSCRIPT_CLIPS_ROOT (callers' voices: only ever sent to signed-in contributors).
    """

    class Transcript(models.TextChoices):
        PENDING = "pending", "To transcribe"
        SUBMITTED = "submitted", "Waiting for check"
        VERIFIED = "verified", "Verified"
        UNUSABLE = "unusable", "Unusable"

    class Meaning(models.TextChoices):
        NONE = "", "No meaning yet"
        SUBMITTED = "submitted", "Waiting for check"
        VERIFIED = "verified", "Verified"

    source = models.CharField(max_length=30, db_index=True, help_text="sheng_radio, sheng_talk, …")
    audio = models.CharField(max_length=255, unique=True, help_text="WAV path relative to TRANSCRIPT_CLIPS_ROOT")
    episode = models.CharField(max_length=160, blank=True, help_text="Episode folder or recording date")
    start = models.CharField(max_length=40, blank=True, help_text="Offset in the episode (s) or stream time")
    duration = models.FloatField(default=0)
    speech_score = models.FloatField(null=True, blank=True)
    music_score = models.FloatField(null=True, blank=True)
    draft = models.TextField(blank=True, help_text="Riba's transcript")
    draft_confidence = models.FloatField(null=True, blank=True, db_index=True, help_text="Mean token probability")

    text = models.TextField(blank=True, help_text="What is said, word for word")
    transcript_status = models.CharField(max_length=9, choices=Transcript.choices, default=Transcript.PENDING, db_index=True)
    transcribed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    transcript_verified_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    meaning_en = models.TextField(blank=True)
    meaning_sw = models.TextField(blank=True, help_text="Standard Swahili")
    meaning_drafts = models.JSONField(default=dict, blank=True,
                                      help_text='Machine suggestions: {"en": [{"by": "risto", "text": …}], "sw": […]}')
    meaning_status = models.CharField(max_length=9, choices=Meaning.choices, default=Meaning.NONE, blank=True, db_index=True)
    meaning_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    meaning_verified_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["draft_confidence", "id"]

    def __str__(self):
        return self.audio


class LexiconWord(Claimable):
    """A Sheng dictionary entry (sheng.co.ke) to check: is the English meaning right, what is it in standard Swahili."""

    class Status(models.TextChoices):
        PENDING = "pending", "To check"
        SUBMITTED = "submitted", "Waiting for check"
        VERIFIED = "verified", "Verified"

    term = models.CharField(max_length=80)
    pos = models.CharField(max_length=30, blank=True)
    meanings_en = models.JSONField(default=list, help_text="English meanings from the dictionary")
    examples = models.JSONField(default=list, help_text='[{"text": Sheng, "en": English}]')
    synonyms = models.JSONField(default=list)

    en_ok = models.BooleanField(null=True, help_text="Is the dictionary's English meaning right?")
    en_correction = models.CharField(max_length=300, blank=True)
    sw = models.JSONField(default=list, help_text="Standard Swahili equivalents")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    verified_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["term"]
        constraints = [models.UniqueConstraint(fields=["term", "pos"], name="unique_lexicon_word")]

    def __str__(self):
        return f"{self.term} ({self.pos})"


class Contribution(models.Model):
    """One action by one contributor. `author` is whose work a check was about, for approval rates."""

    class Kind(models.TextChoices):
        TRANSCRIBE = "transcribe", "Transcribed a clip"
        VERIFY_TRANSCRIPT = "verify_transcript", "Checked a transcript"
        MEANING = "meaning", "Added a meaning"
        VERIFY_MEANING = "verify_meaning", "Checked a meaning"
        WORD = "word", "Checked a dictionary word"
        VERIFY_WORD = "verify_word", "Verified a dictionary check"
        SKIP = "skip", "Skipped"

    class Verdict(models.TextChoices):
        NONE = "", "—"
        APPROVE = "approve", "Approved"
        FIX = "fix", "Fixed"
        REJECT = "reject", "Rejected"

    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="contributions")
    kind = models.CharField(max_length=17, choices=Kind.choices, db_index=True)
    clip = models.ForeignKey(SpeechClip, null=True, blank=True, on_delete=models.CASCADE, related_name="contributions")
    word = models.ForeignKey(LexiconWord, null=True, blank=True, on_delete=models.CASCADE, related_name="contributions")
    verdict = models.CharField(max_length=7, choices=Verdict.choices, default=Verdict.NONE, blank=True)
    author = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="checked_contributions")
    data = models.JSONField(default=dict, blank=True, help_text="What was submitted")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} {self.kind} {self.verdict}"

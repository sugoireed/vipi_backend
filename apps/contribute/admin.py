from django.contrib import admin

from .models import Contribution, LexiconWord, SpeechClip


@admin.register(SpeechClip)
class SpeechClipAdmin(admin.ModelAdmin):
    list_display = ("audio", "source", "duration", "draft_confidence", "transcript_status", "meaning_status", "transcribed_by")
    list_filter = ("transcript_status", "meaning_status", "source")
    search_fields = ("audio", "episode", "draft", "text", "meaning_en", "meaning_sw")
    readonly_fields = ("audio", "source", "episode", "start", "duration", "speech_score", "music_score", "draft",
                       "draft_confidence")


@admin.register(LexiconWord)
class LexiconWordAdmin(admin.ModelAdmin):
    list_display = ("term", "pos", "status", "en_ok", "reviewed_by", "verified_by")
    list_filter = ("status", "en_ok", "pos")
    search_fields = ("term", "en_correction")


@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "verdict", "author", "clip", "word")
    list_filter = ("kind", "verdict")
    search_fields = ("user__username", "author__username")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

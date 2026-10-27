from django.contrib import admin

from .models import TranslationLog


@admin.register(TranslationLog)
class TranslationLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "direction", "language", "status", "latency_ms", "audio_seconds", "client", "earbuds")
    list_filter = ("status", "direction", "language", "client")
    search_fields = ("user__username", "earbuds", "error")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

from django.conf import settings
from django.db import models
from django.utils import timezone


class TranslationLog(models.Model):
    """One live translation through the proxy. Audio is never stored."""

    class Direction(models.TextChoices):
        TO_EN = "to_en", "Swahili/Sheng → English"
        TO_SW = "to_sw", "English → Swahili"

    class Status(models.TextChoices):
        OK = "ok", "OK"
        SILENCE = "silence", "No speech"
        ERROR = "error", "Engine error"
        QUOTA = "quota", "Blocked: no pass / quota"

    class Client(models.TextChoices):
        APP = "app", "App + own earbuds"
        POD = "pod", "Vipi! Pods"
        CASE = "case", "Talk Case"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="translations")
    pass_used = models.ForeignKey("billing.Pass", null=True, blank=True, on_delete=models.SET_NULL)
    direction = models.CharField(max_length=6, choices=Direction.choices)
    language = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OK, db_index=True)
    audio_seconds = models.FloatField(default=0)
    latency_ms = models.PositiveIntegerField(default=0, help_text="Engine round trip measured on the server")
    model = models.CharField(max_length=40, blank=True)
    client = models.CharField(max_length=6, choices=Client.choices, default=Client.APP)
    earbuds = models.CharField(max_length=60, blank=True, help_text="Earbud model reported by the app")
    app_version = models.CharField(max_length=20, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.direction} {self.status} {self.latency_ms}ms"

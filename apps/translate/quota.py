from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from apps.billing.models import Pass

from .models import TranslationLog


@dataclass
class Allowance:
    allowed: bool
    active_pass: Pass | None
    free_remaining: int
    reason: str = ""


def allowance(user) -> Allowance:
    """Active pass (own purchase or B2B seat) = unlimited; otherwise N free translations a day."""
    p = Pass.active_for(user)
    if p:
        return Allowance(True, p, settings.FREE_DAILY_TRANSLATIONS)
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    used = TranslationLog.objects.filter(
        user=user, created_at__gte=start, status__in=[TranslationLog.Status.OK, TranslationLog.Status.SILENCE]
    ).count()
    left = max(0, settings.FREE_DAILY_TRANSLATIONS - used)
    if left == 0:
        return Allowance(False, None, 0, "Free translations for today are used up. Get a day pass to keep going.")
    return Allowance(True, None, left)

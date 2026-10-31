from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()

_P = {
    "cash": '<rect x="2" y="6" width="20" height="12" rx="3"/><circle cx="12" cy="12" r="2.5"/><path d="M6 10v4M18 10v4"/>',
    "ticket": '<path d="M3 8a2 2 0 0 0 0 4v4h18v-4a2 2 0 0 1 0-4V4H3z"/><path d="M13 4v16" stroke-dasharray="2 2"/>',
    "wave": '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "pods": '<circle cx="8" cy="8" r="4"/><path d="M8 12v8"/><circle cx="17" cy="9" r="3"/><path d="M17 12v6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "pin": '<path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    # sidebar and top bar
    "home": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>',
    "swap": '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
    "case": '<rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="13" r="3.5"/><path d="M9 7.5h6"/>',
    "users": '<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 4.5a3.2 3.2 0 0 1 0 6.3M18 20a6 6 0 0 0-2.5-4.9"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    "bell": '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6.5 2 6.5H4S6 14 6 9"/><path d="M10 19a2 2 0 0 0 4 0"/>',
    "logout": '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 16l-4-4 4-4M6 12h10"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h10"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "arrow": '<path d="M7 17 17 7M9 7h8v8"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/>',
    "lock": '<rect x="5" y="10" width="14" height="10" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="3"/><path d="M11 18.5h2"/>',
    "pen": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "verify": '<path d="M12 3 5 6v6c0 4.2 3 7.6 7 9 4-1.4 7-4.8 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "chat": '<path d="M5 5h14v10H9l-4 4z"/><path d="M9 9h6M9 12h4"/>',
    "book": '<path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h10"/>',
    "shield": '<path d="M12 3 5 6v6c0 4.2 3 7.6 7 9 4-1.4 7-4.8 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
}


@register.simple_tag
def icon(name, size=22):
    p = _P.get(name, _P["wave"])
    return mark_safe(f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" '
                     f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{p}</svg>')


_BADGE = {
    # devices
    "available": "green", "reserved": "blue", "rented": "orange", "charging": "purple",
    "maintenance": "amber", "lost": "red", "retired": "grey",
    # payments
    "paid": "green", "pending": "amber", "failed": "red", "cancelled": "grey", "refunded": "purple",
    # rentals
    "active": "orange", "returned": "green",
    # translations
    "ok": "green", "silence": "grey", "error": "red", "quota": "amber",
    # deposit
    "held": "blue", "released": "green", "captured": "orange", "none": "grey",
}


@register.simple_tag
def badge(value, label=None):
    tone = _BADGE.get(str(value), "grey")
    return mark_safe(f'<span class="badge b-{tone}">{label or str(value).replace("_", " ").capitalize()}</span>')


@register.filter
def kes(v):
    try:
        return f"KES {int(v):,}"
    except (TypeError, ValueError):
        return "—"


@register.filter
def initials(user):
    name = (user.get_full_name() or user.username or "?").strip()
    parts = name.replace("@", " ").split()
    return "".join(p[0] for p in parts[:2]).upper()


@register.simple_tag
def site_url(path=""):
    """The marketing site's address (settings.SITE_URL), for links back to it."""
    return f"{getattr(settings, 'SITE_URL', 'https://vipikenya.com')}{path}"

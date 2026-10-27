from django import template
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

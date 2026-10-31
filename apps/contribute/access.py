"""Who may contribute: staff, plus people invited into the Contributors group (who don't see the ops dashboard)."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.urls import reverse

GROUP = "Contributors"


def is_contributor(user):
    return user.is_authenticated and user.is_active and (user.is_staff or user.groups.filter(name=GROUP).exists())


def contributor_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("contribute:login"))
        if not is_contributor(request.user):
            raise PermissionDenied("Contributors only")
        return view(request, *args, **kwargs)
    return wrapped

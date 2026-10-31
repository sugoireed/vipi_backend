"""Who may use the ops dashboard: active staff only.

Anyone can sign up at /dashboard/signup/, but a new account is never staff. It lands in the
"Dashboard access requests" group and sees the pending page until an admin ticks "Staff status"
for it in /admin/. Signed-in people without staff (travellers from the app, contributors) get the
same pending page instead of a bare 403.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render
from django.urls import reverse

REQUEST_GROUP = "Dashboard access requests"


def staff_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("dashboard:login"))
        if not (user.is_active and user.is_staff):
            return render(request, "dashboard/auth/pending.html", status=403)
        return view(request, *args, **kwargs)
    return wrapped

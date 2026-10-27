"""Staff dashboard: overview, fleet, rentals, payments, usage, customers."""
import json
import statistics
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Organisation
from apps.billing.models import Pass, Payment, Plan
from apps.esim.models import EsimOrder
from apps.fleet.models import Device, DeviceEvent, Kiosk, Rental
from apps.translate.models import TranslationLog

User = get_user_model()

STATUS_COLORS = {
    "available": "#22A55A", "reserved": "#3B82F6", "rented": "#FF6B00", "charging": "#7C3AED",
    "maintenance": "#F5A524", "lost": "#E5484D", "retired": "#9A9AA5",
}


def _days(n):
    today = timezone.localdate()
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _series(qs, field, n=30, agg=None):
    """Daily counts (or sums) for the last n days, zero-filled."""
    start = timezone.localdate() - timedelta(days=n - 1)
    rows = (qs.filter(**{f"{field}__date__gte": start}).annotate(d=TruncDate(field)).values("d")
            .annotate(v=Sum(agg) if agg else Count("id")))
    by = {r["d"]: r["v"] or 0 for r in rows}
    days = _days(n)
    return [d.strftime("%d %b") for d in days], [by.get(d, 0) for d in days]


def _pct(values, p):
    if not values:
        return 0
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(p / 100 * (len(values) - 1))))
    return values[k]


def _ctx(request, active, **kw):
    overdue = Rental.objects.filter(status=Rental.Status.ACTIVE, due_at__lt=timezone.now()).count()
    return {"active": active, "nav_overdue": overdue, "now": timezone.now(), **kw}


@staff_member_required
def overview(request):
    now = timezone.now()
    d30 = now - timedelta(days=30)
    d7 = now - timedelta(days=7)
    today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)

    paid = Payment.objects.filter(status=Payment.Status.PAID)
    revenue_30 = paid.filter(paid_at__gte=d30).aggregate(s=Sum("amount_kes"))["s"] or 0
    revenue_prev = paid.filter(paid_at__gte=d30 - timedelta(days=30), paid_at__lt=d30).aggregate(s=Sum("amount_kes"))["s"] or 0
    active_passes = Pass.objects.filter(cancelled=False, starts_at__lte=now, ends_at__gt=now).count()
    tl = TranslationLog.objects.all()
    trans_today = tl.filter(created_at__gte=today, status=TranslationLog.Status.OK).count()
    trans_30 = tl.filter(created_at__gte=d30, status=TranslationLog.Status.OK).count()
    lat = list(tl.filter(created_at__gte=d7, status=TranslationLog.Status.OK).values_list("latency_ms", flat=True))
    p50, p95 = (int(statistics.median(lat)) if lat else 0), _pct(lat, 95)
    err_7 = tl.filter(created_at__gte=d7, status=TranslationLog.Status.ERROR).count()
    total_7 = tl.filter(created_at__gte=d7).exclude(status=TranslationLog.Status.QUOTA).count()
    error_rate = round(100 * err_7 / total_7, 1) if total_7 else 0

    fleet = dict(Device.objects.values_list("status").annotate(n=Count("id")))
    fleet_total = sum(fleet.values())
    out = fleet.get("rented", 0)
    in_service = fleet_total - fleet.get("retired", 0) - fleet.get("lost", 0)
    utilisation = round(100 * out / in_service) if in_service else 0
    overdue = Rental.objects.filter(status=Rental.Status.ACTIVE, due_at__lt=now).select_related("user", "pickup_kiosk")
    upcoming = (Rental.objects.filter(status=Rental.Status.RESERVED, reserved_for__lte=now + timedelta(hours=48))
                .select_related("user", "pickup_kiosk", "payment").order_by("reserved_for")[:8])

    labels, t_ok = _series(tl.filter(status=TranslationLog.Status.OK), "created_at")
    _, t_err = _series(tl.filter(status__in=[TranslationLog.Status.ERROR, TranslationLog.Status.QUOTA]), "created_at")
    _, rev = _series(paid, "paid_at", agg="amount_kes")
    rev_by_kind = (paid.filter(paid_at__gte=d30).values("plan__kind").annotate(s=Sum("amount_kes")).order_by("-s"))
    kind_labels = dict(Plan.Kind.choices)

    charts = {
        "labels": labels, "ok": t_ok, "err": t_err, "rev": rev,
        "fleet_labels": [Device.Status(k).label for k in fleet], "fleet_values": list(fleet.values()),
        "fleet_colors": [STATUS_COLORS.get(k, "#999") for k in fleet],
        "mix_labels": [kind_labels.get(r["plan__kind"], "Other") for r in rev_by_kind],
        "mix_values": [r["s"] for r in rev_by_kind],
    }
    return render(request, "dashboard/overview.html", _ctx(
        request, "overview",
        kpis=[
            {"label": "Revenue · 30 days", "value": f"KES {revenue_30:,}", "sub": _delta(revenue_30, revenue_prev), "tone": "purple", "icon": "cash"},
            {"label": "Active passes", "value": f"{active_passes:,}", "sub": "app + kit + business", "tone": "orange", "icon": "ticket"},
            {"label": "Translations today", "value": f"{trans_today:,}", "sub": f"{trans_30:,} in 30 days", "tone": "blue", "icon": "wave"},
            {"label": "Latency p50 / p95", "value": f"{p50/1000:.2f}s", "sub": f"p95 {p95/1000:.2f}s · {error_rate}% errors (7d)", "tone": "green" if p50 and p50 < 2000 else "orange", "icon": "bolt"},
            {"label": "Kits out now", "value": f"{out}", "sub": f"{utilisation}% fleet utilisation", "tone": "orange", "icon": "pods"},
            {"label": "Overdue rentals", "value": f"{overdue.count()}", "sub": "follow up today" if overdue else "all on time", "tone": "red" if overdue else "green", "icon": "clock"},
        ],
        charts=json.dumps(charts),
        overdue=overdue[:6],
        upcoming=upcoming,
        recent_payments=Payment.objects.select_related("user", "plan")[:8],
    ))


def _delta(now_v, prev_v):
    if not prev_v:
        return "first 30 days"
    pct = round(100 * (now_v - prev_v) / prev_v)
    return f"{'▲' if pct >= 0 else '▼'} {abs(pct)}% vs previous 30 days"


@staff_member_required
def fleet(request):
    kiosks = Kiosk.objects.filter(active=True).annotate(
        available=Count("devices", filter=Q(devices__status=Device.Status.AVAILABLE), distinct=True),
        charging=Count("devices", filter=Q(devices__status=Device.Status.CHARGING), distinct=True),
        maintenance=Count("devices", filter=Q(devices__status=Device.Status.MAINTENANCE), distinct=True),
        pods=Count("devices", filter=Q(devices__kind=Device.Kind.POD_PAIR, devices__status=Device.Status.AVAILABLE), distinct=True),
        cases=Count("devices", filter=Q(devices__kind=Device.Kind.TALK_CASE, devices__status=Device.Status.AVAILABLE), distinct=True),
        upcoming=Count("pickups", filter=Q(pickups__status=Rental.Status.RESERVED), distinct=True),
    )
    devices = Device.objects.select_related("kiosk")
    f_status, f_kind, f_kiosk, q = (request.GET.get(k, "") for k in ("status", "kind", "kiosk", "q"))
    if f_status:
        devices = devices.filter(status=f_status)
    if f_kind:
        devices = devices.filter(kind=f_kind)
    if f_kiosk:
        devices = devices.filter(kiosk__code=f_kiosk)
    if q:
        devices = devices.filter(Q(serial__icontains=q) | Q(notes__icontains=q))
    counts = dict(Device.objects.values_list("status").annotate(n=Count("id")))
    page = Paginator(devices, 40).get_page(request.GET.get("page"))
    qs_no_page = request.GET.copy()
    qs_no_page.pop("page", None)
    return render(request, "dashboard/fleet.html", _ctx(
        request, "fleet", kiosks=kiosks, devices=page, page=page, qs=qs_no_page.urlencode(),
        status_choices=[(k, v, counts.get(k, 0), STATUS_COLORS[k]) for k, v in Device.Status.choices],
        kind_choices=Device.Kind.choices, f=dict(status=f_status, kind=f_kind, kiosk=f_kiosk, q=q),
        all_kiosks=Kiosk.objects.filter(active=True),
    ))


@staff_member_required
@require_POST
def device_action(request, serial):
    d = get_object_or_404(Device, serial=serial)
    action = request.POST.get("action")
    if action == "ready" and d.status in (Device.Status.CHARGING, Device.Status.MAINTENANCE):
        d.status = Device.Status.AVAILABLE
        d.save()
        d.log(DeviceEvent.Kind.READY, by=request.user)
    elif action == "maintenance" and d.status != Device.Status.RENTED:
        d.status = Device.Status.MAINTENANCE
        d.save()
        d.log(DeviceEvent.Kind.MAINTENANCE, by=request.user)
    elif action == "move":
        k = get_object_or_404(Kiosk, code=request.POST.get("kiosk"))
        d.kiosk = k
        d.save()
        d.log(DeviceEvent.Kind.MOVED, by=request.user, kiosk=k)
    messages.success(request, f"{d.serial}: {d.get_status_display()}")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:fleet")


@staff_member_required
def rentals(request):
    tab = request.GET.get("tab", "today")
    now = timezone.now()
    qs = Rental.objects.select_related("user", "pickup_kiosk", "plan", "payment").prefetch_related("devices")
    tabs = {
        "today": qs.filter(status=Rental.Status.RESERVED).order_by("reserved_for"),
        "active": qs.filter(status=Rental.Status.ACTIVE, due_at__gte=now).order_by("due_at"),
        "overdue": qs.filter(status=Rental.Status.ACTIVE, due_at__lt=now).order_by("due_at"),
        "returned": qs.filter(status__in=[Rental.Status.RETURNED, Rental.Status.LOST, Rental.Status.CANCELLED]).order_by("-returned_at", "-created_at"),
    }
    counts = {k: v.count() for k, v in tabs.items()}
    return render(request, "dashboard/rentals.html", _ctx(
        request, "rentals", tab=tab, rentals=tabs.get(tab, tabs["today"])[:100], counts=counts,
        kiosks=Kiosk.objects.filter(active=True),
    ))


@staff_member_required
@require_POST
def rental_action(request, code):
    r = get_object_or_404(Rental, code=code)
    action = request.POST.get("action")
    try:
        if action == "checkout":
            if r.payment and r.payment.status != Payment.Status.PAID:
                if request.POST.get("collect") == "cash":
                    r.payment.method = Payment.Method.CASH
                    r.payment.save()
                    r.payment.mark_paid(provider_ref=f"KIOSK-{request.user.username}")
                else:
                    raise ValueError("Payment not received yet — collect cash or wait for M-Pesa.")
            pods = Device.objects.filter(kiosk=r.pickup_kiosk, kind=Device.Kind.POD_PAIR, status=Device.Status.AVAILABLE).first()
            case = Device.objects.filter(kiosk=r.pickup_kiosk, kind=Device.Kind.TALK_CASE, status=Device.Status.AVAILABLE).first()
            kit = [d for d in (pods, case) if d]
            if not pods:
                raise ValueError(f"No pods available at {r.pickup_kiosk}.")
            r.check_out(kit, by=request.user)
            messages.success(request, f"{r.code} handed over: {', '.join(d.serial for d in kit)}")
        elif action == "checkin":
            kiosk = get_object_or_404(Kiosk, code=request.POST.get("kiosk") or r.pickup_kiosk.code)
            fee = int(request.POST.get("damage_fee") or 0)
            r.check_in(kiosk, by=request.user, damage_fee_kes=fee, note=request.POST.get("note", ""))
            extra = f" · late fee KES {r.late_fee_kes:,}" if r.late_fee_kes else ""
            messages.success(request, f"{r.code} returned at {kiosk}{extra}")
        elif action == "lost":
            r.mark_lost(by=request.user, note=request.POST.get("note", ""))
            messages.warning(request, f"{r.code} marked lost — deposit captured.")
        elif action == "cancel" and r.status == Rental.Status.RESERVED:
            r.status = Rental.Status.CANCELLED
            r.save()
            messages.info(request, f"{r.code} cancelled.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:rentals")


@staff_member_required
def payments(request):
    qs = Payment.objects.select_related("user", "plan")
    st, method, q = (request.GET.get(k, "") for k in ("status", "method", "q"))
    if st:
        qs = qs.filter(status=st)
    if method:
        qs = qs.filter(method=method)
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(provider_ref__icontains=q) | Q(phone__icontains=q) | Q(user__username__icontains=q))
    d30 = timezone.now() - timedelta(days=30)
    by_method = (Payment.objects.filter(status=Payment.Status.PAID, paid_at__gte=d30).values("method")
                 .annotate(s=Sum("amount_kes"), n=Count("id")).order_by("-s"))
    pending = Payment.objects.filter(status=Payment.Status.PENDING).count()
    return render(request, "dashboard/payments.html", _ctx(
        request, "payments", payments=qs[:200], by_method=[{**r, "label": Payment.Method(r["method"]).label} for r in by_method],
        pending=pending, f=dict(status=st, method=method, q=q),
        esim_failed=EsimOrder.objects.filter(status=EsimOrder.Status.FAILED).select_related("user", "bundle__plan", "payment")[:20],
        esim_counts=dict(EsimOrder.objects.values_list("status").annotate(n=Count("id"))),
        status_choices=Payment.Status.choices, method_choices=Payment.Method.choices,
    ))


@staff_member_required
@require_POST
def payment_action(request, reference):
    p = get_object_or_404(Payment, reference=reference)
    if request.POST.get("action") == "confirm":
        p.mark_paid(provider_ref=f"MANUAL-{request.user.username}")
        messages.success(request, f"{p.reference} confirmed — pass granted.")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:payments")


@staff_member_required
def usage(request):
    tl = TranslationLog.objects.all()
    d30 = timezone.now() - timedelta(days=30)
    recent = tl.filter(created_at__gte=d30)
    labels, to_en = _series(tl.filter(direction="to_en", status="ok"), "created_at")
    _, to_sw = _series(tl.filter(direction="to_sw", status="ok"), "created_at")
    lang = list(recent.filter(status="ok").values("language").annotate(n=Count("id")).order_by("-n"))
    clients = list(recent.values("client").annotate(n=Count("id")).order_by("-n"))
    earbuds = (recent.exclude(earbuds="").values("earbuds")
               .annotate(n=Count("id"), errors=Count("id", filter=Q(status="error"))).order_by("-n")[:10])
    lat = list(recent.filter(status="ok").values_list("latency_ms", flat=True))
    buckets = [0, 800, 1200, 1600, 2000, 2500, 3000, 4000, 10 ** 9]
    hist = [sum(1 for v in lat if lo <= v < hi) for lo, hi in zip(buckets, buckets[1:])]
    hist_labels = ["<0.8s", "0.8–1.2", "1.2–1.6", "1.6–2.0", "2.0–2.5", "2.5–3.0", "3–4s", ">4s"]
    audio_hours = (recent.aggregate(s=Sum("audio_seconds"))["s"] or 0) / 3600
    charts = {"labels": labels, "to_en": to_en, "to_sw": to_sw,
              "lang_labels": [r["language"] or "?" for r in lang], "lang_values": [r["n"] for r in lang],
              "hist_labels": hist_labels, "hist": hist}
    client_labels = dict(TranslationLog.Client.choices)
    return render(request, "dashboard/usage.html", _ctx(
        request, "usage", charts=json.dumps(charts),
        stats=[
            {"label": "Translations · 30 days", "value": f"{recent.filter(status='ok').count():,}"},
            {"label": "Audio processed", "value": f"{audio_hours:.1f} h"},
            {"label": "Median latency", "value": f"{(statistics.median(lat) / 1000 if lat else 0):.2f} s"},
            {"label": "Under 2 s", "value": f"{round(100 * sum(1 for v in lat if v < 2000) / len(lat)) if lat else 0}%"},
        ],
        clients=[{"label": client_labels.get(c["client"], c["client"]), "n": c["n"]} for c in clients],
        earbuds=earbuds,
        errors=tl.filter(status__in=["error", "quota"]).select_related("user")[:15],
    ))


@staff_member_required
def customers(request):
    q = request.GET.get("q", "")
    now = timezone.now()
    users = (User.objects.filter(is_staff=False).select_related("profile", "profile__organisation")
             .annotate(
                 n_trans=Coalesce(Subquery(TranslationLog.objects.filter(user=OuterRef("pk"), status="ok")
                                           .values("user").annotate(c=Count("id")).values("c")[:1]), Value(0), output_field=IntegerField()),
                 spent=Coalesce(Subquery(Payment.objects.filter(user=OuterRef("pk"), status="paid")
                                         .values("user").annotate(s=Sum("amount_kes")).values("s")[:1]), Value(0), output_field=IntegerField()),
                 active_pass=Coalesce(Subquery(Pass.objects.filter(user=OuterRef("pk"), starts_at__lte=now, ends_at__gt=now, cancelled=False)
                                               .values("user").annotate(c=Count("id")).values("c")[:1]), Value(0), output_field=IntegerField()))
             .order_by("-date_joined"))
    if q:
        users = users.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(profile__phone__icontains=q) | Q(profile__country__icontains=q))
    countries = (User.objects.filter(is_staff=False).exclude(profile__country="").values("profile__country")
                 .annotate(n=Count("id")).order_by("-n")[:8])
    orgs = Organisation.objects.annotate(members_n=Count("members"))
    return render(request, "dashboard/customers.html", _ctx(
        request, "customers", users=users[:150], countries=countries, orgs=orgs, q=q,
        total=User.objects.filter(is_staff=False).count(),
    ))

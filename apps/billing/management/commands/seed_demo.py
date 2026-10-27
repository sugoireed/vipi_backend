"""Creates plans, kiosks, devices and (optionally) 45 days of demo activity.

    python manage.py seed_demo            # plans + kiosks + fleet only (safe for production)
    python manage.py seed_demo --activity # also fake customers, payments, rentals, translations
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Organisation
from apps.billing.models import Pass, Payment, Plan
from apps.fleet.models import Device, Kiosk, Rental
from apps.translate.models import TranslationLog

User = get_user_model()

PLANS = [
    # code, name, kind, days, KES, USD, deposit, kit, description, sort
    ("day-pass", "Day pass", "app_pass", 1, 390, "3.00", 0, False, "App on your own phone + earbuds for 24 h", 1),
    ("week-pass", "Week pass", "app_pass", 7, 1950, "15.00", 0, False, "Unlimited translation for 7 days", 2),
    ("trip-pass", "Trip pass", "app_pass", 21, 3250, "25.00", 0, False, "Up to 21 days in Kenya", 3),
    ("kit-day", "Kit rental · per day", "kit_rental", 1, 1040, "8.00", 5000, True, "Pods + Talk Case + eSIM data", 4),
    ("kit-week", "Kit rental · week", "kit_rental", 7, 5850, "45.00", 5000, True, "Pods + Talk Case for 7 days", 5),
    ("pods-buy", "Vipi! Pods (buy)", "purchase", None, 12900, "99.00", 0, False, "Own the pods, 30-day pass included", 6),
    ("biz-seat", "Business seat · month", "b2b_seat", 30, 1950, "15.00", 0, False, "Per guide / desk, billed monthly", 7),
    ("esim-3gb", "Karibu 3 · 3 GB eSIM", "esim_data", 7, 1300, "10.00", 0, False, "3 GB Kenya data for 7 days", 8),
    ("esim-10gb", "Safari 10 · 10 GB eSIM", "esim_data", 15, 2600, "20.00", 0, False, "10 GB Kenya data for 15 days", 9),
    ("esim-20gb", "Explorer 20 · 20 GB eSIM", "esim_data", 30, 3900, "30.00", 0, False, "20 GB Kenya data for 30 days", 10),
]
ESIM_GB = {"esim-3gb": 3, "esim-10gb": 10, "esim-20gb": 20}

KIOSKS = [
    ("jkia-t1a", "JKIA Terminal 1A arrivals", "airport", "Nairobi", 40),
    ("jkia-t1e", "JKIA Terminal 1E arrivals", "airport", "Nairobi", 30),
    ("moi-mba", "Moi Int'l Airport, Mombasa", "airport", "Mombasa", 25),
    ("westlands", "Westlands partner hotel desk", "hotel", "Nairobi", 15),
    ("diani", "Diani beach partner resort", "hotel", "Kwale", 15),
    ("mara-camp", "Maasai Mara camp desk", "operator", "Narok", 12),
    ("depot", "Vipi! depot, Kilimani", "office", "Nairobi", 60),
]

COUNTRIES = ["United States", "United Kingdom", "Germany", "France", "Italy", "China", "India", "Netherlands",
             "Canada", "Australia", "Spain", "South Africa"]
FIRST = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Lukas", "Sofia", "Wei", "Priya", "Jack", "Chloé", "Marco",
         "Hannah", "Arjun", "Mia", "Daniel", "Zoe", "Ethan", "Lena", "Sam"]
LAST = ["Smith", "Johnson", "Müller", "Martin", "Rossi", "Chen", "Patel", "Brown", "Dubois", "Garcia", "Jansen", "Taylor"]
EARBUDS = ["AirPods Pro 2", "AirPods 4", "Galaxy Buds3", "Pixel Buds Pro", "Oraimo FreePods 4", "Sony WF-1000XM5",
           "Vipi! Pods VP-1", "Jabra Elite", "Beats Studio Buds"]


class Command(BaseCommand):
    help = "Seed plans, kiosks and fleet; --activity adds demo customers and 45 days of usage."

    def add_arguments(self, parser):
        parser.add_argument("--activity", action="store_true")
        parser.add_argument("--admin", default="", help="email:password for a superuser to create")

    def handle(self, *args, **opts):
        rnd = random.Random(42)
        for code, name, kind, days, kes, usd, dep, kit, desc, sort in PLANS:
            Plan.objects.update_or_create(code=code, defaults=dict(
                name=name, kind=kind, duration_days=days, price_kes=kes, price_usd=Decimal(usd), deposit_kes=dep,
                includes_kit=kit, description=desc, sort=sort, active=True))
        from apps.esim.models import EsimBundle
        for code, gb in ESIM_GB.items():
            plan = Plan.objects.get(code=code)
            EsimBundle.objects.update_or_create(plan=plan, defaults=dict(
                data_gb=gb, validity_days=plan.duration_days, provider="sandbox"))
        kiosks = []
        for code, name, kind, city, cap in KIOSKS:
            k, _ = Kiosk.objects.update_or_create(code=code, defaults=dict(name=name, kind=kind, city=city, capacity=cap))
            kiosks.append(k)
        if not Device.objects.exists():
            n = 0
            for k in kiosks:
                for _ in range(max(4, k.capacity // 3)):
                    n += 1
                    Device.objects.create(serial=f"VP1-{n:04d}", kind=Device.Kind.POD_PAIR, model="VP-1 (pilot ODM)",
                                          firmware="0.9.2", kiosk=k, purchase_cost_usd=Decimal("21.50"))
                for _ in range(max(2, k.capacity // 6)):
                    n += 1
                    Device.objects.create(serial=f"VT1-{n:04d}", kind=Device.Kind.TALK_CASE, model="VT-1 proto",
                                          firmware="0.3.0", kiosk=k, purchase_cost_usd=Decimal("48.00"))
        if opts["admin"]:
            email, _, pw = opts["admin"].partition(":")
            if not User.objects.filter(username=email).exists():
                User.objects.create_superuser(username=email, email=email, password=pw, first_name="Sensei")
        self.stdout.write(self.style.SUCCESS(f"Plans {Plan.objects.count()}, kiosks {Kiosk.objects.count()}, devices {Device.objects.count()}"))
        if opts["activity"]:
            self._activity(rnd, kiosks)

    def _activity(self, rnd, kiosks):
        now = timezone.now()
        plans = {p.code: p for p in Plan.objects.all()}
        orgs = [Organisation.objects.get_or_create(name=n, defaults=dict(kind=k, seats=s, contact_name=c))[0]
                for n, k, s, c in [("Savanna Trails Safaris", "safari", 24, "Wanjiru K."),
                                   ("Coastline Resorts Group", "hotel", 12, "Ali M."),
                                   ("Mara Plains Guides Co-op", "safari", 18, "Lemayian S.")]]
        users = []
        for i in range(140):
            fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
            email = f"{fn.lower()}.{ln.lower()}{i}@example.com"
            u, created = User.objects.get_or_create(username=email, defaults=dict(email=email, first_name=fn, last_name=ln))
            if created:
                u.set_unusable_password()
                u.date_joined = now - timedelta(days=rnd.uniform(0, 45))
                u.save()
                u.profile.country = rnd.choice(COUNTRIES)
                u.profile.phone = f"07{rnd.randint(10000000, 99999999)}"
                if i % 23 == 0:
                    u.profile.organisation = rnd.choice(orgs)
                    u.profile.is_guide = True
                u.profile.save()
            users.append(u)

        pods = list(Device.objects.filter(kind=Device.Kind.POD_PAIR))
        cases = list(Device.objects.filter(kind=Device.Kind.TALK_CASE))
        for u in users:
            joined = u.date_joined
            # Payments / passes
            r = rnd.random()
            if r < 0.55:
                plan = plans[rnd.choices(["day-pass", "week-pass", "trip-pass"], [5, 3, 2])[0]]
                when = joined + timedelta(hours=rnd.uniform(1, 30))
                if when < now:
                    method = rnd.choices(["mpesa", "card"], [3, 2])[0]
                    p = Payment.objects.create(user=u, plan=plan, amount_kes=plan.price_kes, method=method, created_at=when,
                                               phone=u.profile.phone, description=plan.name)
                    if rnd.random() < 0.9:
                        p.mark_paid(provider_ref=f"S{rnd.randint(10**8, 10**9)}", when=when + timedelta(seconds=40))
                    else:
                        p.mark_failed("Request cancelled by user")
            elif r < 0.75:
                plan = plans[rnd.choice(["kit-day", "kit-week"])]
                days = rnd.randint(2, 6) if plan.code == "kit-day" else 7
                qty = days if plan.code == "kit-day" else 1
                when = joined + timedelta(hours=rnd.uniform(0, 12))
                p = Payment.objects.create(user=u, plan=plan, quantity=qty, amount_kes=plan.price_kes * qty + plan.deposit_kes,
                                           method="mpesa", created_at=when, phone=u.profile.phone, description=plan.name)
                kiosk = rnd.choice(kiosks[:6])
                rent = Rental.objects.create(user=u, plan=plan, payment=p, pickup_kiosk=kiosk, days=days,
                                             reserved_for=when + timedelta(hours=rnd.uniform(1, 20)), deposit_kes=plan.deposit_kes,
                                             flight=rnd.choice(["KQ101", "EK719", "QR1341", "BA65", "TK607", "ET308", ""]), created_at=when)
                if rent.reserved_for < now:
                    p.mark_paid(provider_ref=f"S{rnd.randint(10**8, 10**9)}", when=when + timedelta(seconds=50))
                    avail_p = [d for d in pods if d.status == Device.Status.AVAILABLE]
                    avail_c = [d for d in cases if d.status == Device.Status.AVAILABLE]
                    kit = [avail_p.pop()] + ([avail_c.pop()] if avail_c and rnd.random() < 0.7 else [])
                    rent.check_out(kit, when=rent.reserved_for)
                    back = rent.reserved_for + timedelta(days=days, hours=rnd.uniform(-20, 30))
                    if back < now and rnd.random() < 0.97:
                        rent.check_in(rnd.choice(kiosks[:6]), when=back)
                        for d in kit:
                            if rnd.random() < 0.85:
                                d.refresh_from_db()
                                d.status = Device.Status.AVAILABLE
                                d.save()
                    elif back < now:
                        rent.mark_lost(note="Customer unreachable")
            # Translations
            pass_ = Pass.objects.filter(user=u).first()
            n = rnd.randint(3, 9) if not pass_ else rnd.randint(15, 90)
            for _ in range(n):
                if pass_:
                    t = pass_.starts_at + (pass_.ends_at - pass_.starts_at) * rnd.random()
                else:
                    t = joined + timedelta(hours=rnd.uniform(0, 48))
                if t > now:
                    continue
                st = rnd.choices(["ok", "silence", "error", "quota"], [93, 3, 2, 2 if not pass_ else 0])[0]
                lat = int(max(600, rnd.gauss(1450, 380) + (900 if rnd.random() < 0.06 else 0)))
                TranslationLog.objects.create(
                    user=u, pass_used=pass_, direction=rnd.choices(["to_en", "to_sw"], [7, 3])[0],
                    language=rnd.choices(["sheng", "swahili", "mixed", "english"], [38, 34, 22, 6])[0] if st == "ok" else ("silence" if st == "silence" else ""),
                    status=st, latency_ms=lat if st in ("ok", "silence") else 0, audio_seconds=round(rnd.uniform(1.5, 14), 1),
                    model="gemini-2.5-flash", client=rnd.choices(["app", "pod", "case"], [70, 20, 10])[0],
                    earbuds=rnd.choice(EARBUDS), app_version="0.1.0", created_at=t,
                    error="Gemini 503: model overloaded" if st == "error" else "")
        # Kits out right now (two of them overdue) and pickups coming up
        renters = rnd.sample([u for u in users if not u.rentals.exists()], 9)
        for i, u in enumerate(renters):
            plan = plans["kit-day"]
            days = rnd.randint(2, 5)
            kiosk = kiosks[i % 3]
            started = now - timedelta(days=days + 1.3) if i < 2 else now - timedelta(days=rnd.uniform(0.2, 1.5))
            if i >= 6:
                started = now + timedelta(hours=rnd.uniform(3, 40))
            p = Payment.objects.create(user=u, plan=plan, quantity=days, amount_kes=plan.price_kes * days + plan.deposit_kes,
                                       method="mpesa", created_at=min(now, started) - timedelta(hours=2), phone=u.profile.phone, description=plan.name)
            rent = Rental.objects.create(user=u, plan=plan, payment=p, pickup_kiosk=kiosk, days=days, reserved_for=started,
                                         deposit_kes=plan.deposit_kes, flight=rnd.choice(["KQ101", "EK719", "QR1341", "BA65"]))
            if i < 8:
                p.mark_paid(provider_ref=f"S{rnd.randint(10**8, 10**9)}", when=min(now, started) - timedelta(hours=1))
            if started < now:
                kit = [Device.objects.filter(kiosk=kiosk, kind=Device.Kind.POD_PAIR, status=Device.Status.AVAILABLE).first(),
                       Device.objects.filter(kiosk=kiosk, kind=Device.Kind.TALK_CASE, status=Device.Status.AVAILABLE).first()]
                rent.check_out([d for d in kit if d], when=started)
        # A few devices in repair
        for d in rnd.sample([d for d in Device.objects.filter(status=Device.Status.AVAILABLE)], 4):
            d.status = Device.Status.MAINTENANCE
            d.notes = "Left bud not charging"
            d.save()
        self.stdout.write(self.style.SUCCESS(
            f"Demo: {User.objects.filter(is_staff=False).count()} customers, {Payment.objects.count()} payments, "
            f"{Rental.objects.count()} rentals, {TranslationLog.objects.count()} translations"))

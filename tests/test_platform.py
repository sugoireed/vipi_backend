import io
import struct
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Pass, Payment, Plan
from apps.fleet.models import Device, Kiosk, Rental
from apps.translate.models import TranslationLog

User = get_user_model()


def wav(seconds=2.0, rate=16000):
    n = int(seconds * rate)
    data = b"\x00\x00" * n
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data))
    f = io.BytesIO(header + data)
    f.name = "clip.wav"
    return f


ENGINE_OK = ({"transcript": "niaje msee", "language": "sheng", "swahili": "habari rafiki", "english": "hey buddy",
              "notes": "", "sheng_terms": [{"term": "msee", "meaning": "guy"}]}, 1234, "gemini-2.5-flash")


@override_settings(FREE_DAILY_TRANSLATIONS=2, GEMINI_API_KEY="test")
class PlatformTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.c = APIClient()
        r = self.c.post("/api/v1/auth/register/", {"email": "Emma@Example.com", "password": "safari-2026!", "name": "Emma Smith",
                                                    "phone": "0712345678", "country": "United States"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.user = User.objects.get(username="emma@example.com")
        self.c.credentials(HTTP_AUTHORIZATION="Token " + r.json()["token"])

    def test_health_and_plans_public(self):
        anon = APIClient()
        self.assertEqual(anon.get("/api/v1/health/").status_code, 200)
        codes = [p["code"] for p in anon.get("/api/v1/plans/").json()]
        self.assertIn("day-pass", codes)

    @mock.patch("apps.translate.engine.translate_clip", return_value=ENGINE_OK)
    def test_free_quota_then_blocked(self, _):
        for _i in range(2):
            r = self.c.post("/api/v1/translate/", {"audio": wav(), "direction": "to_en"}, format="multipart")
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["english"], "hey buddy")
        self.assertEqual(r.json()["free_translations_left_today"], 0)
        r = self.c.post("/api/v1/translate/", {"audio": wav(), "direction": "to_en"}, format="multipart")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(TranslationLog.objects.filter(user=self.user, status="quota").count(), 1)

    @mock.patch("apps.translate.engine.translate_clip", return_value=ENGINE_OK)
    def test_pass_unlimited(self, _):
        Pass.grant(self.user, Plan.objects.get(code="day-pass"))
        for _i in range(4):
            r = self.c.post("/api/v1/translate/", {"audio": wav(), "direction": "to_sw", "earbuds": "Oraimo FreePods 4"}, format="multipart")
            self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["free_translations_left_today"])
        self.assertEqual(TranslationLog.objects.filter(user=self.user, status="ok", earbuds="Oraimo FreePods 4").count(), 4)

    def test_rejects_long_clip(self):
        r = self.c.post("/api/v1/translate/", {"audio": wav(40), "direction": "to_en"}, format="multipart")
        self.assertEqual(r.status_code, 400)

    @mock.patch("apps.billing.mpesa.is_configured", return_value=True)
    @mock.patch("apps.billing.mpesa._token", return_value="tok")
    @mock.patch("apps.billing.mpesa.requests.post")
    def test_mpesa_purchase_and_callback_grants_pass(self, post, *_):
        post.return_value = mock.Mock(status_code=200, content=b"x", json=lambda: {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_1"})
        r = self.c.post("/api/v1/purchase/", {"plan": "week-pass", "method": "mpesa", "phone": "0712345678"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        ref = r.json()["reference"]
        self.assertEqual(Payment.objects.get(reference=ref).phone, "254712345678")
        cb = {"Body": {"stkCallback": {"CheckoutRequestID": "ws_CO_1", "ResultCode": 0, "ResultDesc": "ok",
               "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 1950}, {"Name": "MpesaReceiptNumber", "Value": "SJK1"}]}}}}
        APIClient().post("/api/v1/payments/mpesa/callback", cb, format="json")
        self.assertEqual(self.c.get(f"/api/v1/payments/{ref}/").json()["status"], "paid")
        me = self.c.get("/api/v1/me/").json()
        self.assertEqual(me["active_pass"]["plan"], "Week pass")
        p = Pass.active_for(self.user)
        self.assertAlmostEqual((p.ends_at - p.starts_at).days, 7)
        # Callback replay is idempotent
        APIClient().post("/api/v1/payments/mpesa/callback", cb, format="json")
        self.assertEqual(Pass.objects.filter(user=self.user).count(), 1)

    def test_bad_phone_fails_payment(self):
        r = self.c.post("/api/v1/purchase/", {"plan": "day-pass", "method": "mpesa", "phone": "12"}, format="json")
        self.assertEqual(r.status_code, 402)

    def test_rental_flow_checkout_late_return(self):
        kiosk = Kiosk.objects.get(code="jkia-t1a")
        r = self.c.post("/api/v1/rentals/", {"kiosk": "jkia-t1a", "plan": "kit-day", "days": 3, "method": "cash"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        rental = Rental.objects.get(code=r.json()["code"])
        self.assertEqual(rental.payment.amount_kes, 1040 * 3 + 5000)
        rental.payment.mark_paid("CASH")
        pods = Device.objects.filter(kiosk=kiosk, kind="pod_pair", status="available").first()
        start = timezone.now() - timedelta(days=4, hours=2)
        rental.check_out([pods], when=start)
        pods.refresh_from_db()
        self.assertEqual(pods.status, "rented")
        self.assertTrue(rental.is_overdue)
        rental.check_in(kiosk)
        pods.refresh_from_db()
        self.assertEqual(pods.status, "charging")
        self.assertEqual(rental.late_fee_kes, 2 * 1040)
        self.assertEqual(rental.deposit_status, "captured")
        # A charging device can't be handed out again until staff mark it ready.
        with self.assertRaises(ValueError):
            Rental.objects.create(user=self.user, pickup_kiosk=kiosk).check_out([pods])

    def test_dashboard_pages_render_for_staff(self):
        call_command("seed_demo", "--activity", verbosity=0)
        staff = User.objects.create_user("ops", password="x-strong-pass-1", is_staff=True)
        c = self.client
        c.force_login(staff)
        for url in ["/dashboard/", "/dashboard/fleet/", "/dashboard/rentals/?tab=overdue", "/dashboard/rentals/?tab=active",
                    "/dashboard/payments/", "/dashboard/usage/", "/dashboard/customers/", "/admin/"]:
            self.assertEqual(c.get(url).status_code, 200, url)
        self.assertEqual(self.client.__class__().get("/dashboard/").status_code, 302)

    def test_dashboard_checkout_and_checkin_actions(self):
        staff = User.objects.create_user("ops2", password="x-strong-pass-1", is_staff=True)
        self.client.force_login(staff)
        kiosk = Kiosk.objects.get(code="jkia-t1a")
        plan = Plan.objects.get(code="kit-day")
        pay = Payment.objects.create(user=self.user, plan=plan, amount_kes=6040, method="cash")
        rental = Rental.objects.create(user=self.user, plan=plan, payment=pay, pickup_kiosk=kiosk, days=1, deposit_kes=5000)
        self.client.post(f"/dashboard/rentals/{rental.code}/", {"action": "checkout", "collect": "cash"})
        rental.refresh_from_db()
        self.assertEqual(rental.status, "active")
        self.assertEqual(rental.devices.count(), 2)
        self.assertTrue(Pass.active_for(self.user))
        self.client.post(f"/dashboard/rentals/{rental.code}/", {"action": "checkin", "kiosk": "westlands"})
        rental.refresh_from_db()
        self.assertEqual(rental.status, "returned")
        self.assertEqual(rental.deposit_status, "released")
        self.assertEqual(set(rental.devices.values_list("status", flat=True)), {"charging"})

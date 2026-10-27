from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.billing.models import Pass, Payment
from apps.esim.models import EsimOrder
from apps.esim.providers import ProviderError, SandboxProvider


@override_settings(ESIM={"PROVIDER": "sandbox", "AIRALO_BASE_URL": "", "AIRALO_CLIENT_ID": "", "AIRALO_CLIENT_SECRET": ""})
class EsimTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.c = APIClient()
        r = self.c.post("/api/v1/auth/register/", {"email": "wei@example.com", "password": "karibu-2026!", "phone": "0712345678"}, format="json")
        self.c.credentials(HTTP_AUTHORIZATION="Token " + r.json()["token"])

    def _buy(self, bundle="esim-3gb"):
        r = self.c.post("/api/v1/esim/orders/", {"bundle": bundle, "method": "card"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return EsimOrder.objects.get(reference=r.json()["reference"])

    def test_bundles_public(self):
        data = APIClient().get("/api/v1/esim/bundles/").json()
        self.assertEqual([b["code"] for b in data], ["esim-3gb", "esim-10gb", "esim-20gb"])
        self.assertEqual(data[0]["price_kes"], 1300)

    def test_paid_order_is_provisioned_with_install_links(self):
        order = self._buy()
        self.assertEqual(order.status, "pending_payment")
        with self.captureOnCommitCallbacks(execute=True):
            order.payment.mark_paid("CARD-1")
        r = self.c.get(f"/api/v1/esim/orders/{order.reference}/").json()
        self.assertIn(r["status"], ("ready", "installed"))
        self.assertTrue(r["install"]["lpa"].startswith("LPA:1$"))
        self.assertTrue(r["install"]["ios_url"].startswith("https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA:1$"))
        self.assertTrue(r["install"]["android_url"].startswith("https://esimsetup.android.com/"))
        self.assertEqual(r["data_total_mb"], 3072)
        qr = self.c.get(f"/api/v1/esim/orders/{order.reference}/qr.png")
        self.assertEqual(qr["Content-Type"], "image/png")
        # Data bundles never grant a translation pass.
        self.assertIsNone(Pass.active_for(order.user))

    def test_repeat_payment_callback_does_not_reorder(self):
        order = self._buy()
        with self.captureOnCommitCallbacks(execute=True):
            order.payment.mark_paid("CARD-1")
        lpa = EsimOrder.objects.get(pk=order.pk).lpa
        with self.captureOnCommitCallbacks(execute=True):
            Payment.objects.get(pk=order.payment.pk).mark_paid("CARD-1")
        self.assertEqual(EsimOrder.objects.get(pk=order.pk).lpa, lpa)

    def test_provider_failure_marks_failed_after_retries(self):
        order = self._buy("esim-10gb")
        with mock.patch.object(SandboxProvider, "create_order", side_effect=ProviderError("down")) as m:
            with self.captureOnCommitCallbacks(execute=True):
                order.payment.mark_paid("CARD-2")
        order.refresh_from_db()
        self.assertEqual(order.status, "failed")
        self.assertEqual(m.call_count, 3)
        r = self.c.get(f"/api/v1/esim/orders/{order.reference}/").json()
        self.assertIsNone(r["install"])

    def test_usage_refresh_and_privacy(self):
        order = self._buy()
        with self.captureOnCommitCallbacks(execute=True):
            order.payment.mark_paid("CARD-3")
        r = self.c.get(f"/api/v1/esim/orders/{order.reference}/").json()
        self.assertGreater(r["data_used_mb"], 0)
        self.assertEqual(r["status"], "installed")
        other = APIClient()
        t = other.post("/api/v1/auth/register/", {"email": "x@example.com", "password": "another-2026!"}, format="json").json()["token"]
        other.credentials(HTTP_AUTHORIZATION="Token " + t)
        self.assertEqual(other.get(f"/api/v1/esim/orders/{order.reference}/").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/esim/orders/{order.reference}/qr.png").status_code, 404)

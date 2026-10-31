"""Dashboard access: sign in, sign up (pending until an admin approves), staff-only pages."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from apps.dashboard.access import REQUEST_GROUP

User = get_user_model()
PAGES = ["/dashboard/", "/dashboard/fleet/", "/dashboard/rentals/", "/dashboard/payments/", "/dashboard/usage/", "/dashboard/customers/"]


class DashboardAuthTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("ops@vipikenya.com", "ops@vipikenya.com", "Kiosk-Nairobi-2026", is_staff=True, first_name="Amani")

    def test_anonymous_is_sent_to_dashboard_login(self):
        r = self.client.get("/dashboard/fleet/")
        self.assertRedirects(r, "/dashboard/login/?next=/dashboard/fleet/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/dashboard/login/"), "Welcome back")

    def test_staff_can_sign_in_and_see_every_page(self):
        r = self.client.post("/dashboard/login/", {"username": "OPS@vipikenya.com ", "password": "Kiosk-Nairobi-2026"})
        self.assertRedirects(r, "/dashboard/", fetch_redirect_response=False)
        for url in PAGES:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_wrong_password_shows_friendly_error(self):
        r = self.client.post("/dashboard/login/", {"username": "ops@vipikenya.com", "password": "nope"})
        self.assertContains(r, "email and password don")

    def test_signup_creates_a_pending_account_that_cannot_see_data(self):
        r = self.client.post("/dashboard/signup/", {"name": "Baraka Mwangi", "email": "Baraka@vipikenya.com", "phone": "0712345678",
                                                   "password1": "Kiosk-Mombasa-2026", "password2": "Kiosk-Mombasa-2026"})
        self.assertRedirects(r, "/dashboard/pending/", fetch_redirect_response=False)
        u = User.objects.get(username="baraka@vipikenya.com")
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.groups.filter(name=REQUEST_GROUP).exists())
        for url in PAGES:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 403, url)
            self.assertContains(r, "Waiting for approval", status_code=403)

    def test_signup_rejects_existing_email_and_mismatched_passwords(self):
        r = self.client.post("/dashboard/signup/", {"name": "X Y", "email": "ops@vipikenya.com", "password1": "Kiosk-Mombasa-2026", "password2": "Kiosk-Mombasa-2026"})
        self.assertContains(r, "already exists")
        r = self.client.post("/dashboard/signup/", {"name": "X Y", "email": "new@vipikenya.com", "password1": "Kiosk-Mombasa-2026", "password2": "different-2026"})
        self.assertContains(r, "don&#x27;t match")
        self.assertFalse(User.objects.filter(username="new@vipikenya.com").exists())

    def test_approved_account_gets_in(self):
        self.client.post("/dashboard/signup/", {"name": "Baraka Mwangi", "email": "baraka@vipikenya.com", "password1": "Kiosk-Mombasa-2026", "password2": "Kiosk-Mombasa-2026"})
        User.objects.filter(username="baraka@vipikenya.com").update(is_staff=True)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)

    def test_password_reset_sends_a_dashboard_link(self):
        r = self.client.post("/dashboard/password-reset/", {"email": "ops@vipikenya.com"})
        self.assertRedirects(r, "/dashboard/password-reset/sent/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/dashboard/password-reset/", mail.outbox[0].body)

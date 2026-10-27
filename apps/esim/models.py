import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def new_esim_ref():
    return f"E-{secrets.token_hex(3).upper()}"


class EsimBundle(models.Model):
    """Data details for a Plan of kind 'esim_data' (price lives on the Plan)."""

    plan = models.OneToOneField("billing.Plan", on_delete=models.CASCADE, related_name="esim_bundle")
    data_gb = models.DecimalField(max_digits=6, decimal_places=1)
    validity_days = models.PositiveIntegerField()
    coverage = models.CharField(max_length=60, default="Kenya")
    provider = models.CharField(max_length=20, default="sandbox", help_text="sandbox | airalo")
    provider_package_id = models.CharField(max_length=120, blank=True,
                                           help_text="The partner's package id, e.g. an Airalo package slug")

    def __str__(self):
        return f"{self.plan.name} · {self.data_gb} GB / {self.validity_days} d"


class EsimOrder(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Waiting for payment"
        PROVISIONING = "provisioning", "Ordering from provider"
        READY = "ready", "Ready to install"
        INSTALLED = "installed", "Installed"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed — refund needed"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.CharField(max_length=12, unique=True, default=new_esim_ref)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="esim_orders")
    bundle = models.ForeignKey(EsimBundle, on_delete=models.PROTECT, related_name="orders")
    payment = models.OneToOneField("billing.Payment", null=True, blank=True, on_delete=models.SET_NULL, related_name="esim_order")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    provider = models.CharField(max_length=20, blank=True)
    provider_order_id = models.CharField(max_length=80, blank=True)
    iccid = models.CharField(max_length=32, blank=True, db_index=True)
    # Secrets: only ever returned to the order's owner, never logged.
    lpa = models.CharField(max_length=255, blank=True, help_text="LPA:1$<SM-DP+ address>$<activation code>")
    data_total_mb = models.PositiveIntegerField(default=0)
    data_used_mb = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    usage_checked_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "eSIM order"

    def __str__(self):
        return f"{self.reference} · {self.bundle.plan.name} · {self.status}"

    @property
    def smdp_address(self):
        parts = self.lpa.split("$")
        return parts[1] if len(parts) >= 3 else ""

    @property
    def activation_code(self):
        parts = self.lpa.split("$")
        return parts[2] if len(parts) >= 3 else ""

    @property
    def ios_install_url(self):
        return f"https://esimsetup.apple.com/esim_qrcode_provisioning?carddata={self.lpa}" if self.lpa else ""

    @property
    def android_install_url(self):
        return f"https://esimsetup.android.com/esim_qrcode_provisioning?carddata={self.lpa}" if self.lpa else ""

    @property
    def data_left_mb(self):
        return max(0, self.data_total_mb - self.data_used_mb)

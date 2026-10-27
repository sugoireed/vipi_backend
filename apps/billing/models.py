import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.dispatch import Signal
from django.utils import timezone

# Sent once when a payment becomes paid: other apps (e.g. eSIM) fulfil their part.
payment_paid = Signal()


def new_reference(prefix="VP"):
    return f"{prefix}-{secrets.token_hex(3).upper()}"


class Plan(models.Model):
    class Kind(models.TextChoices):
        APP_PASS = "app_pass", "App pass (own phone + earbuds)"
        KIT_RENTAL = "kit_rental", "Kit rental (pods + Talk Case)"
        PURCHASE = "purchase", "Device purchase"
        B2B_SEAT = "b2b_seat", "Business seat (monthly)"
        ESIM_DATA = "esim_data", "eSIM data bundle"

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    duration_days = models.PositiveIntegerField(null=True, blank=True, help_text="Empty for one-off purchases")
    price_kes = models.PositiveIntegerField()
    price_usd = models.DecimalField(max_digits=8, decimal_places=2)
    deposit_kes = models.PositiveIntegerField(default=0, help_text="Refundable deposit held for rentals")
    includes_kit = models.BooleanField(default=False)
    description = models.CharField(max_length=240, blank=True)
    active = models.BooleanField(default=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "price_kes"]

    def __str__(self):
        return f"{self.name} (KES {self.price_kes:,})"

    @property
    def gives_pass(self):
        return self.kind in (self.Kind.APP_PASS, self.Kind.KIT_RENTAL, self.Kind.PURCHASE)

    @property
    def pass_days(self):
        # Purchases include a 30-day pass.
        return self.duration_days or 30


class Payment(models.Model):
    class Method(models.TextChoices):
        MPESA = "mpesa", "M-Pesa"
        CARD = "card", "Card"
        CASH = "cash", "Cash at kiosk"
        INVOICE = "invoice", "Invoice (B2B)"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    reference = models.CharField(max_length=20, unique=True, default=new_reference)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    description = models.CharField(max_length=160, blank=True)
    quantity = models.PositiveIntegerField(default=1, help_text="Days for per-day plans, else 1")
    amount_kes = models.PositiveIntegerField()
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.MPESA)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    phone = models.CharField(max_length=20, blank=True)
    checkout_request_id = models.CharField(max_length=64, blank=True, db_index=True)
    provider_ref = models.CharField(max_length=64, blank=True, help_text="M-Pesa receipt / card transaction id")
    failure_reason = models.CharField(max_length=240, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} · KES {self.amount_kes:,} · {self.status}"

    @transaction.atomic
    def mark_paid(self, provider_ref="", raw=None, when=None):
        """Idempotent: marks paid and grants the pass the plan includes."""
        if self.status == self.Status.PAID:
            return self
        self.status = self.Status.PAID
        self.provider_ref = provider_ref or self.provider_ref
        self.paid_at = when or timezone.now()
        if raw:
            self.raw = {**self.raw, "callback": raw}
        self.save()
        if self.plan and self.plan.gives_pass and self.user:
            Pass.grant(self.user, self.plan, payment=self, start=self.paid_at,
                       days=self.plan.pass_days * max(1, self.quantity))
        transaction.on_commit(lambda: payment_paid.send(sender=Payment, payment=self))
        return self

    def mark_failed(self, reason="", raw=None):
        if self.status == self.Status.PAID:
            return self
        self.status = self.Status.FAILED
        self.failure_reason = reason[:240]
        if raw:
            self.raw = {**self.raw, "callback": raw}
        self.save()
        return self


class Pass(models.Model):
    class Source(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        B2B = "b2b", "Business seat"
        COMP = "comp", "Complimentary"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passes")
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL)
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.SET_NULL)
    payment = models.OneToOneField(Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="granted_pass")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.PURCHASE)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    cancelled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-ends_at"]
        verbose_name_plural = "passes"

    def __str__(self):
        return f"{self.user} · {self.plan or self.source} → {self.ends_at:%d %b %Y}"

    @property
    def is_active(self):
        now = timezone.now()
        return not self.cancelled and self.starts_at <= now < self.ends_at

    @classmethod
    def active_for(cls, user):
        now = timezone.now()
        return (cls.objects.filter(user=user, cancelled=False, starts_at__lte=now, ends_at__gt=now)
                .order_by("-ends_at").first())

    @classmethod
    def grant(cls, user, plan, payment=None, start=None, source=Source.PURCHASE, organisation=None, days=None):
        """New passes stack on top of an existing active pass."""
        start = start or timezone.now()
        current = cls.active_for(user)
        if current and current.ends_at > start:
            start = current.ends_at
        return cls.objects.create(
            user=user, plan=plan, payment=payment, source=source, organisation=organisation,
            starts_at=start, ends_at=start + timedelta(days=days or (plan.pass_days if plan else 30)),
        )

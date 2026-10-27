import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


def new_rental_code():
    return f"R-{secrets.token_hex(3).upper()}"


class Kiosk(models.Model):
    """A pickup / return point: airport desk, partner hotel, operator office."""

    class Kind(models.TextChoices):
        AIRPORT = "airport", "Airport desk"
        HOTEL = "hotel", "Partner hotel"
        OPERATOR = "operator", "Tour operator"
        OFFICE = "office", "Vipi! office / depot"

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.AIRPORT)
    city = models.CharField(max_length=60, default="Nairobi")
    address = models.CharField(max_length=200, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.SET_NULL)
    opening_hours = models.CharField(max_length=80, default="06:00–23:00")
    capacity = models.PositiveIntegerField(default=40, help_text="Charging dock slots")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Device(models.Model):
    class Kind(models.TextChoices):
        POD_PAIR = "pod_pair", "Vipi! Pods (pair)"
        TALK_CASE = "talk_case", "Vipi! Talk Case"

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        RENTED = "rented", "Rented"
        CHARGING = "charging", "Charging / cleaning"
        MAINTENANCE = "maintenance", "Maintenance"
        LOST = "lost", "Lost"
        RETIRED = "retired", "Retired"

    serial = models.CharField(max_length=32, unique=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    model = models.CharField(max_length=40, default="VP-1", help_text="VP-1, VT-1 or a white-label model during pilot")
    firmware = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE, db_index=True)
    kiosk = models.ForeignKey(Kiosk, null=True, blank=True, on_delete=models.SET_NULL, related_name="devices")
    battery_cycles = models.PositiveIntegerField(default=0)
    purchase_cost_usd = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    purchased_at = models.DateField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["serial"]

    def __str__(self):
        return f"{self.serial} ({self.get_kind_display()})"

    def log(self, kind, by=None, rental=None, kiosk=None, note=""):
        DeviceEvent.objects.create(device=self, kind=kind, by=by, rental=rental, kiosk=kiosk or self.kiosk, note=note)


class Rental(models.Model):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        ACTIVE = "active", "Out with customer"
        RETURNED = "returned", "Returned"
        LOST = "lost", "Lost / not returned"
        CANCELLED = "cancelled", "Cancelled"

    class Deposit(models.TextChoices):
        NONE = "none", "No deposit"
        HELD = "held", "Held"
        RELEASED = "released", "Released"
        CAPTURED = "captured", "Captured (fees)"

    code = models.CharField(max_length=12, unique=True, default=new_rental_code)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rentals")
    plan = models.ForeignKey("billing.Plan", null=True, blank=True, on_delete=models.SET_NULL)
    payment = models.ForeignKey("billing.Payment", null=True, blank=True, on_delete=models.SET_NULL, related_name="rentals")
    pickup_kiosk = models.ForeignKey(Kiosk, on_delete=models.PROTECT, related_name="pickups")
    return_kiosk = models.ForeignKey(Kiosk, null=True, blank=True, on_delete=models.SET_NULL, related_name="returns")
    devices = models.ManyToManyField(Device, blank=True, related_name="rentals")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RESERVED, db_index=True)
    reserved_for = models.DateTimeField(default=timezone.now, help_text="Expected pickup time (e.g. flight arrival)")
    days = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    deposit_kes = models.PositiveIntegerField(default=0)
    deposit_status = models.CharField(max_length=10, choices=Deposit.choices, default=Deposit.NONE)
    late_fee_kes = models.PositiveIntegerField(default=0)
    damage_fee_kes = models.PositiveIntegerField(default=0)
    flight = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} · {self.user} · {self.status}"

    @property
    def is_overdue(self):
        return self.status == self.Status.ACTIVE and self.due_at and timezone.now() > self.due_at

    @property
    def daily_rate_kes(self):
        if self.plan and self.plan.duration_days:
            return math.ceil(self.plan.price_kes / self.plan.duration_days)
        return 1040

    @transaction.atomic
    def check_out(self, devices, by=None, when=None):
        """Hand the kit to the customer at the pickup kiosk."""
        when = when or timezone.now()
        devices = list(devices)
        busy = [d.serial for d in devices if d.status not in (Device.Status.AVAILABLE, Device.Status.RESERVED)]
        if busy:
            raise ValueError(f"Not available: {', '.join(busy)}")
        self.devices.set(devices)
        for d in devices:
            d.status = Device.Status.RENTED
            d.kiosk = None
            d.last_seen_at = when
            d.save()
            d.log(DeviceEvent.Kind.CHECKED_OUT, by=by, rental=self, kiosk=self.pickup_kiosk)
        self.status = self.Status.ACTIVE
        self.started_at = when
        self.due_at = when + timedelta(days=self.days)
        if self.deposit_kes and self.deposit_status == self.Deposit.NONE:
            self.deposit_status = self.Deposit.HELD
        self.save()
        return self

    @transaction.atomic
    def check_in(self, kiosk, by=None, when=None, damage_fee_kes=0, note=""):
        """Customer returns the kit. Late days are charged at the daily rate."""
        when = when or timezone.now()
        late_days = 0
        if self.due_at and when > self.due_at:
            late_days = math.ceil((when - self.due_at).total_seconds() / 86400)
        self.late_fee_kes = late_days * self.daily_rate_kes
        self.damage_fee_kes = damage_fee_kes
        for d in self.devices.all():
            if d.status == Device.Status.RENTED:
                d.status = Device.Status.CHARGING
                d.kiosk = kiosk
                d.battery_cycles += 1
                d.last_seen_at = when
                d.save()
                d.log(DeviceEvent.Kind.RETURNED, by=by, rental=self, kiosk=kiosk, note=note)
        self.status = self.Status.RETURNED
        self.returned_at = when
        self.return_kiosk = kiosk
        if self.deposit_status == self.Deposit.HELD:
            self.deposit_status = (self.Deposit.CAPTURED if (self.late_fee_kes or self.damage_fee_kes)
                                   else self.Deposit.RELEASED)
        if note:
            self.notes = (self.notes + "\n" + note).strip()
        self.save()
        return self

    @transaction.atomic
    def mark_lost(self, by=None, note=""):
        for d in self.devices.filter(status=Device.Status.RENTED):
            d.status = Device.Status.LOST
            d.save()
            d.log(DeviceEvent.Kind.LOST, by=by, rental=self, note=note)
        self.status = self.Status.LOST
        if self.deposit_status == self.Deposit.HELD:
            self.deposit_status = self.Deposit.CAPTURED
        self.save()
        return self


class DeviceEvent(models.Model):
    class Kind(models.TextChoices):
        CHECKED_OUT = "checked_out", "Checked out"
        RETURNED = "returned", "Returned"
        READY = "ready", "Ready (charged & cleaned)"
        MOVED = "moved", "Moved to kiosk"
        MAINTENANCE = "maintenance", "Sent to maintenance"
        LOST = "lost", "Reported lost"
        FOUND = "found", "Found"
        NOTE = "note", "Note"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    rental = models.ForeignKey(Rental, null=True, blank=True, on_delete=models.SET_NULL)
    kiosk = models.ForeignKey(Kiosk, null=True, blank=True, on_delete=models.SET_NULL)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Organisation(models.Model):
    """A B2B customer: safari operator, hotel, airline… buying seats for guides/guests."""

    class Kind(models.TextChoices):
        SAFARI = "safari", "Safari / tour operator"
        HOTEL = "hotel", "Hotel / resort"
        AIRLINE = "airline", "Airline / airport"
        CLINIC = "clinic", "Clinic / hospital"
        GOV = "gov", "Government / KWS"
        OTHER = "other", "Other"

    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SAFARI)
    contact_name = models.CharField(max_length=120, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    seats = models.PositiveIntegerField(default=0, help_text="Paid seats (guides/devices) on the B2B plan")
    price_per_seat_kes = models.PositiveIntegerField(default=1950)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def monthly_value_kes(self):
        return self.seats * self.price_per_seat_kes


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=32, blank=True, help_text="M-Pesa / WhatsApp number")
    country = models.CharField(max_length=64, blank=True, help_text="Home country, e.g. United States")
    organisation = models.ForeignKey(Organisation, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    is_guide = models.BooleanField(default=False, help_text="Uses an organisation seat")
    app_version = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile({self.user})"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)

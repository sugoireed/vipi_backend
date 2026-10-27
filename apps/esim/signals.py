from django.dispatch import receiver

from apps.billing.models import Payment, payment_paid

from .models import EsimOrder
from .services import provision


@receiver(payment_paid, sender=Payment)
def provision_on_payment(sender, payment, **kwargs):
    order = EsimOrder.objects.filter(payment=payment).first()
    if order:
        provision(order)

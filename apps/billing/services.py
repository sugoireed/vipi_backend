from django.conf import settings

from . import mpesa
from .models import Payment, Plan


def start_purchase(user, plan: Plan, method: str, phone: str = "", quantity: int = 1) -> Payment:
    """Creates a pending payment. M-Pesa: sends the STK push to the customer's phone.
    Card/cash: stays pending until confirmed (card gateway or kiosk staff)."""
    quantity = max(1, int(quantity or 1))
    payment = Payment.objects.create(
        user=user, plan=plan, quantity=quantity, method=method,
        amount_kes=plan.price_kes * quantity + plan.deposit_kes,
        description=plan.name + (f" × {quantity}" if quantity > 1 else "")
        + (f" + KES {plan.deposit_kes:,} deposit" if plan.deposit_kes else ""),
    )
    if method == Payment.Method.MPESA:
        try:
            payment.phone = mpesa.normalize_phone(phone or getattr(user.profile, "phone", ""))
            data = mpesa.stk_push(payment.phone, payment.amount_kes, payment.reference, plan.name)
            payment.checkout_request_id = data.get("CheckoutRequestID", "")
            payment.raw = {"stk": data}
        except mpesa.MpesaError as e:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = str(e)
        payment.save()
    return payment


def simulate_paid(payment: Payment) -> Payment:
    """DEBUG helper so the app flow can be tested without Daraja credentials."""
    if not settings.DEBUG:
        raise PermissionError("Only available in DEBUG")
    return payment.mark_paid(provider_ref="SIMULATED")

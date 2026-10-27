import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import EsimOrder
from .providers import ProviderError, get_provider

log = logging.getLogger("vipi")
MAX_ATTEMPTS = 3


def provision(order: EsimOrder) -> EsimOrder:
    """Order the eSIM from the provider once the payment is paid. Idempotent and retried up to 3 times."""
    with transaction.atomic():
        order = EsimOrder.objects.select_for_update().get(pk=order.pk)
        if order.status not in (EsimOrder.Status.PENDING_PAYMENT, EsimOrder.Status.PROVISIONING, EsimOrder.Status.FAILED):
            return order
        if order.lpa:  # already provisioned
            return order
        order.status = EsimOrder.Status.PROVISIONING
        order.save(update_fields=["status"])
    provider = get_provider(order.bundle.provider)
    last_error = ""
    while order.attempts < MAX_ATTEMPTS:
        order.attempts += 1
        try:
            res = provider.create_order(order.bundle, order.reference)
            now = timezone.now()
            order.provider = provider.name
            order.provider_order_id = res.provider_order_id
            order.iccid = res.iccid
            order.lpa = res.lpa
            order.data_total_mb = res.data_total_mb
            order.status = EsimOrder.Status.READY
            order.ready_at = now
            order.expires_at = now + timedelta(days=order.bundle.validity_days)
            order.error = ""
            order.save()
            return order
        except ProviderError as e:
            last_error = str(e)
            log.warning("eSIM provisioning %s attempt %s failed: %s", order.reference, order.attempts, e)
    order.status = EsimOrder.Status.FAILED
    order.error = last_error[:300]
    order.save()
    return order


def refresh_usage(order: EsimOrder, max_age_seconds=60) -> EsimOrder:
    if order.status not in (EsimOrder.Status.READY, EsimOrder.Status.INSTALLED) or not order.iccid:
        return order
    if order.usage_checked_at and (timezone.now() - order.usage_checked_at).total_seconds() < max_age_seconds:
        return order
    try:
        u = get_provider(order.provider or order.bundle.provider).get_usage(order)
    except ProviderError as e:
        log.info("usage refresh failed for %s: %s", order.reference, e)
        return order
    order.data_total_mb = u.data_total_mb or order.data_total_mb
    order.data_used_mb = u.data_used_mb
    if order.status == EsimOrder.Status.READY and u.data_used_mb > 0:
        order.status = EsimOrder.Status.INSTALLED
    if order.expires_at and timezone.now() > order.expires_at:
        order.status = EsimOrder.Status.EXPIRED
    order.usage_checked_at = timezone.now()
    order.save()
    return order

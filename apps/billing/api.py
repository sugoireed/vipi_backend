import json
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import mpesa
from .models import Pass, Payment, Plan
from .services import simulate_paid, start_purchase

log = logging.getLogger("vipi")


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["code", "name", "kind", "duration_days", "price_kes", "price_usd", "deposit_kes", "includes_kit", "description"]


class PaymentSerializer(serializers.ModelSerializer):
    plan = serializers.CharField(source="plan.code", default=None)

    class Meta:
        model = Payment
        fields = ["reference", "plan", "quantity", "amount_kes", "method", "status", "failure_reason", "provider_ref", "created_at", "paid_at"]


class PassSerializer(serializers.ModelSerializer):
    plan = serializers.CharField(source="plan.name", default=None)

    class Meta:
        model = Pass
        fields = ["plan", "source", "starts_at", "ends_at", "is_active"]


class PlanList(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(PlanSerializer(Plan.objects.filter(active=True), many=True).data)


class PurchaseView(APIView):
    """Buy an app pass or a device. Kit rentals go through /rentals/ (they need a kiosk)."""

    def post(self, request):
        plan = get_object_or_404(Plan, code=request.data.get("plan"), active=True)
        if plan.kind not in (Plan.Kind.APP_PASS, Plan.Kind.PURCHASE):
            return Response({"detail": "Book kit rentals via /api/v1/rentals/."}, status=400)
        method = request.data.get("method", Payment.Method.MPESA)
        if method not in (Payment.Method.MPESA, Payment.Method.CARD):
            return Response({"detail": "Pay with mpesa or card."}, status=400)
        payment = start_purchase(request.user, plan, method, request.data.get("phone", ""),
                                 request.data.get("quantity", 1))
        code = status.HTTP_201_CREATED if payment.status != Payment.Status.FAILED else status.HTTP_402_PAYMENT_REQUIRED
        return Response(PaymentSerializer(payment).data, status=code)


class PaymentDetail(APIView):
    def get(self, request, reference):
        p = get_object_or_404(Payment, reference=reference, user=request.user)
        return Response(PaymentSerializer(p).data)


class PaymentSimulate(APIView):
    def post(self, request, reference):
        if not settings.DEBUG:
            return Response(status=404)
        p = get_object_or_404(Payment, reference=reference, user=request.user)
        return Response(PaymentSerializer(simulate_paid(p)).data)


class MyPasses(APIView):
    def get(self, request):
        return Response(PassSerializer(request.user.passes.all()[:20], many=True).data)


class MpesaCallback(APIView):
    """Safaricom posts the STK result here. Always answer 200 so Daraja stops retrying."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        secret = settings.MPESA["CALLBACK_SECRET"]
        if secret and request.query_params.get("k") != secret:
            log.warning("M-Pesa callback with bad secret")
            return Response({"ResultCode": 1, "ResultDesc": "Rejected"})
        body = request.data if isinstance(request.data, dict) else json.loads(request.body or b"{}")
        info = mpesa.parse_callback(body)
        payment = Payment.objects.filter(checkout_request_id=info["checkout_request_id"]).first()
        if not payment:
            log.warning("M-Pesa callback for unknown checkout %s", info["checkout_request_id"])
        elif info["ok"]:
            if info["amount"] is not None and int(float(info["amount"])) < payment.amount_kes:
                payment.mark_failed(f"Paid {info['amount']} < {payment.amount_kes}", raw=body)
            else:
                payment.mark_paid(provider_ref=info["receipt"], raw=body)
        else:
            payment.mark_failed(info["reason"], raw=body)
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

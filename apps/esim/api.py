import io

import segno
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.api import PaymentSerializer
from apps.billing.models import Payment, Plan
from apps.billing.services import start_purchase

from .models import EsimBundle, EsimOrder
from .services import refresh_usage


class BundleSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="plan.code")
    name = serializers.CharField(source="plan.name")
    description = serializers.CharField(source="plan.description")
    price_kes = serializers.IntegerField(source="plan.price_kes")
    price_usd = serializers.DecimalField(source="plan.price_usd", max_digits=8, decimal_places=2)

    class Meta:
        model = EsimBundle
        fields = ["code", "name", "description", "data_gb", "validity_days", "coverage", "price_kes", "price_usd"]


class OrderSerializer(serializers.ModelSerializer):
    bundle = BundleSerializer(read_only=True)
    payment = PaymentSerializer(read_only=True)
    data_left_mb = serializers.IntegerField(read_only=True)
    install = serializers.SerializerMethodField()

    class Meta:
        model = EsimOrder
        fields = ["reference", "status", "bundle", "payment", "iccid", "data_total_mb", "data_used_mb",
                  "data_left_mb", "ready_at", "expires_at", "error", "install"]

    def get_install(self, o):
        if not o.lpa:
            return None
        return {"ios_url": o.ios_install_url, "android_url": o.android_install_url, "lpa": o.lpa,
                "smdp_address": o.smdp_address, "activation_code": o.activation_code}


def _bundles():
    return EsimBundle.objects.select_related("plan").filter(plan__active=True, plan__kind=Plan.Kind.ESIM_DATA).order_by("plan__sort", "plan__price_kes")


class BundleList(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(BundleSerializer(_bundles(), many=True).data)


class OrdersView(APIView):
    def get(self, request):
        qs = request.user.esim_orders.select_related("bundle__plan", "payment")[:20]
        return Response(OrderSerializer(qs, many=True).data)

    def post(self, request):
        bundle = get_object_or_404(_bundles(), plan__code=request.data.get("bundle"))
        method = request.data.get("method", Payment.Method.MPESA)
        if method not in (Payment.Method.MPESA, Payment.Method.CARD):
            return Response({"detail": "Pay with mpesa or card."}, status=400)
        order = EsimOrder.objects.create(user=request.user, bundle=bundle)
        payment = start_purchase(request.user, bundle.plan, method, request.data.get("phone", ""))
        order.payment = payment
        if payment.status == Payment.Status.FAILED:
            order.status = EsimOrder.Status.CANCELLED
            order.error = payment.failure_reason
        order.save()
        code = status.HTTP_201_CREATED if payment.status != Payment.Status.FAILED else status.HTTP_402_PAYMENT_REQUIRED
        return Response(OrderSerializer(order).data, status=code)


class OrderDetail(APIView):
    def get(self, request, reference):
        order = get_object_or_404(EsimOrder.objects.select_related("bundle__plan", "payment"), reference=reference, user=request.user)
        return Response(OrderSerializer(refresh_usage(order)).data)


class OrderQr(APIView):
    def get(self, request, reference):
        order = get_object_or_404(EsimOrder, reference=reference, user=request.user)
        if not order.lpa:
            return Response({"detail": "eSIM not ready yet."}, status=404)
        buf = io.BytesIO()
        segno.make(order.lpa, error="m").save(buf, kind="png", scale=8, border=2)
        resp = HttpResponse(buf.getvalue(), content_type="image/png")
        resp["Cache-Control"] = "private, no-store"
        return resp

from datetime import timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.api import PaymentSerializer
from apps.billing.models import Payment, Plan
from apps.billing.services import start_purchase

from .models import Device, Kiosk, Rental


class KioskSerializer(serializers.ModelSerializer):
    kits_available = serializers.IntegerField(read_only=True)

    class Meta:
        model = Kiosk
        fields = ["code", "name", "kind", "city", "address", "latitude", "longitude", "opening_hours", "kits_available"]


class RentalSerializer(serializers.ModelSerializer):
    pickup_kiosk = serializers.CharField(source="pickup_kiosk.name")
    plan = serializers.CharField(source="plan.name", default=None)
    payment = PaymentSerializer(read_only=True)
    devices = serializers.SlugRelatedField(slug_field="serial", many=True, read_only=True)

    class Meta:
        model = Rental
        fields = ["code", "status", "plan", "days", "pickup_kiosk", "reserved_for", "started_at", "due_at",
                  "returned_at", "deposit_kes", "deposit_status", "late_fee_kes", "damage_fee_kes", "devices", "payment"]


class KioskList(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = Kiosk.objects.filter(active=True).annotate(
            kits_available=Count("devices", filter=Q(devices__status=Device.Status.AVAILABLE, devices__kind=Device.Kind.POD_PAIR)))
        return Response(KioskSerializer(qs, many=True).data)


class RentalsView(APIView):
    def get(self, request):
        return Response(RentalSerializer(request.user.rentals.select_related("pickup_kiosk", "plan", "payment")[:20], many=True).data)

    def post(self, request):
        """Reserve a kit: {kiosk, plan, days, reserved_for?, flight?, method, phone}."""
        kiosk = get_object_or_404(Kiosk, code=request.data.get("kiosk"), active=True)
        plan = get_object_or_404(Plan, code=request.data.get("plan"), kind=Plan.Kind.KIT_RENTAL, active=True)
        days = max(1, min(60, int(request.data.get("days") or 1)))
        # Per-day plans multiply by days; weekly plans count weeks.
        qty = days if (plan.duration_days or 1) == 1 else max(1, -(-days // plan.duration_days))
        when = parse_datetime(request.data.get("reserved_for") or "") or timezone.now()
        if timezone.is_naive(when):
            when = timezone.make_aware(when)
        if when < timezone.now() - timedelta(hours=1):
            return Response({"detail": "Pickup time is in the past."}, status=400)
        method = request.data.get("method", Payment.Method.MPESA)
        if method not in (Payment.Method.MPESA, Payment.Method.CARD, Payment.Method.CASH):
            return Response({"detail": "Pay with mpesa, card or cash."}, status=400)
        payment = start_purchase(request.user, plan, method, request.data.get("phone", ""), qty)
        rental = Rental.objects.create(
            user=request.user, plan=plan, payment=payment, pickup_kiosk=kiosk, reserved_for=when,
            days=qty * (plan.duration_days or 1), deposit_kes=plan.deposit_kes,
            flight=str(request.data.get("flight", ""))[:20],
        )
        code = status.HTTP_201_CREATED if payment.status != Payment.Status.FAILED else status.HTTP_402_PAYMENT_REQUIRED
        return Response(RentalSerializer(rental).data, status=code)

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import permissions, serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.translate.quota import allowance

User = get_user_model()


def me_payload(user):
    a = allowance(user)
    p = a.active_pass
    return {
        "id": user.id,
        "email": user.email,
        "name": user.get_full_name() or user.username,
        "phone": user.profile.phone,
        "country": user.profile.country,
        "organisation": user.profile.organisation.name if user.profile.organisation else None,
        "active_pass": None if not p else {
            "plan": p.plan.name if p.plan else p.get_source_display(),
            "starts_at": p.starts_at,
            "ends_at": p.ends_at,
        },
        "free_translations_left_today": None if p else a.free_remaining,
        "free_daily_limit": settings.FREE_DAILY_TRANSLATIONS,
    }


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    country = serializers.CharField(max_length=64, required=False, allow_blank=True)

    def validate_email(self, v):
        v = v.lower().strip()
        if User.objects.filter(username=v).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return v

    def validate_password(self, v):
        validate_password(v)
        return v


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        first, _, last = (d.get("name") or "").partition(" ")
        user = User.objects.create_user(username=d["email"], email=d["email"], password=d["password"],
                                        first_name=first, last_name=last)
        user.profile.phone = d.get("phone", "")
        user.profile.country = d.get("country", "")
        user.profile.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "me": me_payload(user)}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").lower().strip()
        user = authenticate(request, username=email, password=request.data.get("password") or "")
        if not user:
            return Response({"detail": "Wrong email or password."}, status=status.HTTP_400_BAD_REQUEST)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "me": me_payload(user)})


class MeView(APIView):
    def get(self, request):
        return Response(me_payload(request.user))

    def patch(self, request):
        prof = request.user.profile
        for f in ("phone", "country", "app_version"):
            if f in request.data:
                setattr(prof, f, str(request.data[f])[:64])
        prof.save()
        return Response(me_payload(request.user))

import json
import logging

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import engine
from .models import TranslationLog
from .quota import allowance

log = logging.getLogger("vipi")


class TranslateView(APIView):
    """POST multipart: audio (16 kHz WAV ≤ 30 s), direction (to_en|to_sw), glossary (JSON list),
    client (app|pod|case), earbuds, app_version. Audio is processed in memory and never stored."""
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        user = request.user
        direction = request.data.get("direction", "to_en")
        if direction not in ("to_en", "to_sw"):
            return Response({"detail": "direction must be to_en or to_sw"}, status=400)
        f = request.FILES.get("audio")
        if not f:
            return Response({"detail": "Attach the clip as 'audio'."}, status=400)
        audio = f.read()
        seconds = engine.wav_seconds(audio)
        meta = dict(
            user=user, direction=direction, audio_seconds=round(seconds, 2),
            client=request.data.get("client", "app")[:6], earbuds=request.data.get("earbuds", "")[:60],
            app_version=request.data.get("app_version", "")[:20], model=settings.GEMINI_MODEL,
        )
        a = allowance(user)
        if not a.allowed:
            TranslationLog.objects.create(status=TranslationLog.Status.QUOTA, **meta)
            return Response({"detail": a.reason, "code": "no_pass"}, status=status.HTTP_402_PAYMENT_REQUIRED)
        if seconds > settings.MAX_CLIP_SECONDS + 2:
            return Response({"detail": f"Clips can be up to {settings.MAX_CLIP_SECONDS} seconds."}, status=400)
        try:
            glossary = json.loads(request.data.get("glossary") or "[]")
            if not isinstance(glossary, list):
                glossary = []
        except ValueError:
            glossary = []
        try:
            result, latency, model = engine.translate_clip(audio, direction, glossary)
        except engine.EngineError as e:
            log.warning("engine error: %s", e)
            TranslationLog.objects.create(status=TranslationLog.Status.ERROR, error=str(e)[:300], pass_used=a.active_pass, **meta)
            return Response({"detail": "Translation engine is busy — try again."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        lang = result.get("language", "")
        st = TranslationLog.Status.SILENCE if lang == "silence" else TranslationLog.Status.OK
        TranslationLog.objects.create(status=st, language=lang, latency_ms=latency, pass_used=a.active_pass,
                                      **{**meta, "model": model})
        left = None if a.active_pass else max(0, a.free_remaining - (1 if st == TranslationLog.Status.OK else 0))
        return Response({**result, "latency_ms": latency, "free_translations_left_today": left,
                         "pass_ends_at": a.active_pass.ends_at if a.active_pass else None})


class Health(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        from apps.billing import mpesa
        return Response({"ok": True, "engine": bool(settings.GEMINI_API_KEY), "model": settings.GEMINI_MODEL,
                         "mpesa": mpesa.is_configured()})

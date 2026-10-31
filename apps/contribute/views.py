"""Contribute: invited people transcribe talk clips, add meanings, check Sheng dictionary words, and check each other.

Each task hands out one item at a time (claimed for 15 minutes so two people don't get the same clip) and never
gives anyone their own work to check. A check that changes the work counts as a fix and goes back for another check.
The one exception is the super admin: their saves and fixes count as verified straight away (`trusted`).
"""
import base64
import re
import threading
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from . import drafts
from .access import GROUP, contributor_required
from .models import Contribution, LexiconWord, SpeechClip

User = get_user_model()
K, V = Contribution.Kind, Contribution.Verdict
T, M, W = SpeechClip.Transcript, SpeechClip.Meaning, LexiconWord.Status
CLAIM = timedelta(minutes=15)

TASKS = {
    "transcribe": ("Transcribe clips", "Fix Riba's draft so it says exactly what you hear.", "clip"),
    "verify": ("Check transcripts", "Listen and approve, fix or reject someone else's transcript.", "clip"),
    "meaning": ("Add meanings", "Give the English and standard Swahili meaning of a checked transcript.", "clip"),
    "verify_meaning": ("Check meanings", "Approve or fix someone else's English and Swahili meaning.", "clip"),
    "words": ("Dictionary words", "Is the English meaning of a Sheng word right? What is it in Swahili?", "word"),
    "verify_words": ("Check words", "Approve or fix someone else's dictionary check.", "word"),
}


SOURCES = {"sheng_radio": "Radio", "sheng_talk": "Sheng Talk"}  # SpeechClip.source -> what contributors see


def _source(request):
    """Which clips to work on (all, Radio or Sheng Talk): ?source= picks one and the session remembers it."""
    if "source" in request.GET:
        request.session["clip_source"] = request.GET["source"] if request.GET["source"] in SOURCES else ""
    return request.session.get("clip_source", "")


def clean(text):
    return " ".join(text.split())


def split_words(text):
    return [w for w in (clean(p) for p in re.split(r"[,;/]", text)) if w]


def _queue(task, user, source=""):
    """What is waiting for `task` that `user` may take: never their own work, never what they skipped.
    `source` limits clip tasks to one category (Radio or Sheng Talk)."""
    skipped = Contribution.objects.filter(user=user, kind=K.SKIP)
    if TASKS[task][2] == "clip":
        qs = SpeechClip.objects.exclude(pk__in=skipped.exclude(clip=None).values("clip"))
        if source:
            qs = qs.filter(source=source)
        if task == "transcribe":  # least confident drafts first: they have the most for Riba to learn
            return qs.filter(transcript_status=T.PENDING).order_by(F("draft_confidence").asc(nulls_last=True), "id")
        if task == "verify":
            return qs.filter(transcript_status=T.SUBMITTED).exclude(transcribed_by=user).order_by("id")
        if task == "meaning":
            return qs.filter(transcript_status=T.VERIFIED, meaning_status=M.NONE).order_by("id")
        return qs.filter(meaning_status=M.SUBMITTED).exclude(meaning_by=user).order_by("id")
    qs = LexiconWord.objects.exclude(pk__in=skipped.exclude(word=None).values("word"))
    if task == "words":
        return qs.filter(status=W.PENDING).order_by("term")
    return qs.filter(status=W.SUBMITTED).exclude(reviewed_by=user).order_by("id")


REDO = {"transcribe": K.TRANSCRIBE, "meaning": K.MEANING}  # tasks with a "Back" button


def _redo(task, user, source=""):
    """Clips `user` did `task` on that nobody has touched since, newest first: "Back" lets them change their answer."""
    if task not in REDO:
        return SpeechClip.objects.none()
    last = Contribution.objects.filter(clip=OuterRef("pk")).exclude(kind=K.SKIP).order_by("-created_at")
    qs = (SpeechClip.objects.exclude(meaning_status=M.NONE) if task == "meaning" else
          SpeechClip.objects.exclude(transcript_status=T.PENDING).filter(meaning_status=M.NONE))
    if source:
        qs = qs.filter(source=source)
    return (qs.annotate(last_by=Subquery(last.values("user")[:1]), last_kind=Subquery(last.values("kind")[:1]),
                        last_at=Subquery(last.values("created_at")[:1]))
            .filter(last_by=user.pk, last_kind=REDO[task]).order_by("-last_at"))


def _claim(qs, user):
    now = timezone.now()
    mine = qs.filter(claimed_by=user, claimed_until__gte=now).first()  # e.g. after a page reload
    if mine:
        return mine
    free = Q(claimed_by=None) | Q(claimed_until__lt=now)
    for item in qs.filter(free)[:5]:
        if type(item).objects.filter(free, pk=item.pk).update(claimed_by=user, claimed_until=now + CLAIM):
            return item
    return None


def _release(item):
    type(item).objects.filter(pk=item.pk).update(claimed_by=None, claimed_until=None)


def _audio(clip):
    path = Path(settings.TRANSCRIPT_CLIPS_ROOT) / clip.audio
    # inline, so a clip is only ever sent inside a signed-in contributor's page, never at a shareable URL
    return "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode() if path.exists() else None


def _stats(user):
    done = user.contributions.exclude(kind=K.SKIP)
    checked = Contribution.objects.filter(author=user).exclude(verdict=V.NONE)
    approved = checked.filter(verdict=V.APPROVE).count()
    return {"done": done.count(), "today": done.filter(created_at__date=timezone.localdate()).count(),
            "checked": checked.count(), "approved": approved,
            "rate": round(100 * approved / checked.count()) if checked.count() else None}


@contributor_required
def home(request):
    _source(request)
    cards = [{"task": t, "title": title, "about": about, "waiting": _queue(t, request.user).count(),
              "by_source": [(key, label, _queue(t, request.user, key).count()) for key, label in SOURCES.items()]
              if kind == "clip" else []}
             for t, (title, about, kind) in TASKS.items()]
    clips = SpeechClip.objects.aggregate(
        verified=Count("id", filter=Q(transcript_status=T.VERIFIED)),
        minutes=Sum("duration", filter=Q(transcript_status=T.VERIFIED)),
        meanings=Count("id", filter=Q(meaning_status=M.VERIFIED)))
    words = LexiconWord.objects.filter(status=W.VERIFIED).count()
    return render(request, "contribute/home.html", {
        "active": "home", "cards": cards, "me": _stats(request.user), "clips": clips, "words": words,
        "recent": request.user.contributions.exclude(kind=K.SKIP).select_related("clip", "word")[:8]})


@contributor_required
def task(request, task, pk=None):
    if task not in TASKS:
        return redirect("contribute:home")
    kind = TASKS[task][2]
    model = SpeechClip if kind == "clip" else LexiconWord
    source = _source(request) if kind == "clip" else ""
    redo = _redo(task, request.user, source)
    if request.method == "POST":
        item = get_object_or_404(model, pk=pk)
        again = _redo(task, request.user).filter(pk=item.pk).exists()  # went back to one they'd already saved
        if not again and not _queue(task, request.user).filter(pk=item.pk).exists():
            messages.warning(request, "Someone else already finished that one, here's the next.")
        elif not (again and request.POST.get("action") == "skip"):  # Skip on a revisit leaves it as it was
            error = (_save_clip if kind == "clip" else _save_word)(request, task, item)
            if error:
                messages.error(request, error)
                return redirect("contribute:item", task=task, pk=item.pk)
            if not again:
                _release(item)
        return redirect("contribute:task", task=task)

    queue = _queue(task, request.user, source)
    again = _redo(task, request.user).filter(pk=pk).first() if pk else None
    item = again or (get_object_or_404(_queue(task, request.user), pk=pk) if pk else _claim(queue, request.user))
    title, about, _ = TASKS[task]
    ctx = {"active": task, "task": task, "title": title, "about": about, "item": item, "waiting": queue.count(),
           "source": source, "source_label": SOURCES.get(source, ""),
           "sources": [("", "All", _queue(task, request.user).count())] +
                      [(key, label, _queue(task, request.user, key).count()) for key, label in SOURCES.items()]
                      if kind == "clip" else [],
           "me": _stats(request.user), "trusted": trusted(request.user), "again": again,
           "back": (redo.filter(last_at__lt=again.last_at) if again else redo).first()}
    if kind == "clip":
        ctx["audio"] = _audio(item) if item else None
        if item and task == "meaning" and not item.meaning_en:
            drafts.fill(item)  # usually already done in the background when the transcript was verified
            ctx["suggest"] = {lang: item.meaning_drafts.get(lang, []) for lang in ("en", "sw")}
    return render(request, f"contribute/{kind}.html", ctx)


def _log(request, kind, verdict="", author=None, **refs_and_data):
    refs = {k: refs_and_data.pop(k) for k in ("clip", "word") if k in refs_and_data}
    Contribution.objects.create(user=request.user, kind=kind, verdict=verdict, author=author, data=refs_and_data, **refs)


def trusted(user):
    """Only the super admin may skip the second-person check; staff and contributors never can."""
    return user.is_superuser


def _save_clip(request, task, clip):
    action, user = request.POST.get("action"), request.user
    sure = trusted(user)
    if action == "skip":
        _log(request, K.SKIP, clip=clip, task=task)
        return None
    if task in ("transcribe", "verify"):
        text = clean(request.POST.get("text", ""))
        if action == "unusable":
            author = clip.transcribed_by if task == "verify" else None
            _log(request, K.TRANSCRIBE if task == "transcribe" else K.VERIFY_TRANSCRIPT,
                 V.REJECT if task == "verify" else "", author, clip=clip, unusable=True)
            clip.transcript_status = T.UNUSABLE
            clip.save(update_fields=["transcript_status"])
            return None
        if not text:
            return "Type what is said (or mark the clip unusable)."
        if task == "transcribe":
            _log(request, K.TRANSCRIBE, clip=clip, text=text, draft=clip.draft, trusted=sure)
            clip.text, clip.transcript_status, clip.transcribed_by = text, T.VERIFIED if sure else T.SUBMITTED, user
            clip.transcript_verified_by = user if sure else None
        elif text == clip.text:
            _log(request, K.VERIFY_TRANSCRIPT, V.APPROVE, clip.transcribed_by, clip=clip, text=text)
            clip.transcript_status, clip.transcript_verified_by = T.VERIFIED, user
        else:  # fixed: the fix itself needs someone else's check (unless the super admin made it)
            _log(request, K.VERIFY_TRANSCRIPT, V.FIX, clip.transcribed_by, clip=clip, text=text, was=clip.text,
                 trusted=sure)
            clip.text, clip.transcribed_by = text, user
            if sure:
                clip.transcript_status, clip.transcript_verified_by = T.VERIFIED, user
        clip.save()
        if clip.transcript_status == T.VERIFIED:  # ready for "Add meanings": fetch suggestions in the background
            threading.Thread(target=drafts.fill, args=(clip,), daemon=True).start()
        return None

    en, sw = clean(request.POST.get("en", "")), clean(request.POST.get("sw", ""))
    if task == "verify_meaning" and action == "reject":
        _log(request, K.VERIFY_MEANING, V.REJECT, clip.meaning_by, clip=clip, en=clip.meaning_en, sw=clip.meaning_sw)
        clip.meaning_en, clip.meaning_sw, clip.meaning_status, clip.meaning_by = "", "", M.NONE, None
        clip.save()
        return None
    if not en or not sw:
        return "Give both the English and the standard Swahili meaning."
    if task == "meaning":
        _log(request, K.MEANING, clip=clip, en=en, sw=sw, trusted=sure)
        clip.meaning_en, clip.meaning_sw, clip.meaning_by = en, sw, user
        clip.meaning_status, clip.meaning_verified_by = (M.VERIFIED, user) if sure else (M.SUBMITTED, None)
    elif (en, sw) == (clip.meaning_en, clip.meaning_sw):
        _log(request, K.VERIFY_MEANING, V.APPROVE, clip.meaning_by, clip=clip, en=en, sw=sw)
        clip.meaning_status, clip.meaning_verified_by = M.VERIFIED, user
    else:
        _log(request, K.VERIFY_MEANING, V.FIX, clip.meaning_by, clip=clip, en=en, sw=sw,
             was={"en": clip.meaning_en, "sw": clip.meaning_sw}, trusted=sure)
        clip.meaning_en, clip.meaning_sw, clip.meaning_by = en, sw, user
        if sure:
            clip.meaning_status, clip.meaning_verified_by = M.VERIFIED, user
    clip.save()
    return None


def _save_word(request, task, word):
    action, user = request.POST.get("action"), request.user
    sure = trusted(user)
    if action == "skip":
        _log(request, K.SKIP, word=word, task=task)
        return None
    en_ok = {"yes": True, "no": False}.get(request.POST.get("en_ok"))
    correction, sw = clean(request.POST.get("en_correction", "")), split_words(request.POST.get("sw", ""))
    if en_ok is None:
        return "Say whether the English meaning is right."
    if en_ok is False and not correction:
        return "Give the right English meaning."
    if en_ok:
        correction = ""
    if task == "words":
        _log(request, K.WORD, word=word, en_ok=en_ok, en_correction=correction, sw=sw, trusted=sure)
        word.en_ok, word.en_correction, word.sw, word.reviewed_by = en_ok, correction, sw, user
        word.status, word.verified_by = (W.VERIFIED, user) if sure else (W.SUBMITTED, None)
    elif (en_ok, correction, sw) == (word.en_ok, word.en_correction, word.sw):
        _log(request, K.VERIFY_WORD, V.APPROVE, word.reviewed_by, word=word, en_ok=en_ok, en_correction=correction, sw=sw)
        word.status, word.verified_by = W.VERIFIED, user
    else:
        _log(request, K.VERIFY_WORD, V.FIX, word.reviewed_by, word=word, en_ok=en_ok, en_correction=correction, sw=sw,
             was={"en_ok": word.en_ok, "en_correction": word.en_correction, "sw": word.sw}, trusted=sure)
        word.en_ok, word.en_correction, word.sw, word.reviewed_by = en_ok, correction, sw, user
        if sure:
            word.status, word.verified_by = W.VERIFIED, user
    word.save()
    return None


@contributor_required
@require_POST
def translate(request):
    """Mufti (Swahili <-> English) for the meaning page's "Translate to …" buttons. Never falls back to Gemini."""
    text, source = clean(request.POST.get("text", "")), request.POST.get("source")
    if source not in ("en", "sw") or not text:
        return JsonResponse({"error": "Nothing to translate."}, status=400)
    out = drafts._translate(text, source, "sw" if source == "en" else "en", "mufti")
    if not out:  # engine down, or Mufti's output failed the engine's checks (e.g. looping on spelled-out numbers)
        return JsonResponse({"error": "Mufti couldn't give a usable translation of this one. Please type it yourself."},
                            status=502)
    return JsonResponse({"translation": out})


@staff_member_required
def people(request):
    group, _ = Group.objects.get_or_create(name=GROUP)
    if request.method == "POST":
        email, name = request.POST.get("email", "").strip().lower(), clean(request.POST.get("name", ""))
        if not email or "@" not in email:
            messages.error(request, "Enter the contributor's email.")
            return redirect("contribute:people")
        user, created = User.objects.get_or_create(username=email, defaults={"email": email})
        if created:
            user.first_name, _, user.last_name = name.partition(" ")
            user.set_unusable_password()
            user.save()
        user.groups.add(group)
        link = request.build_absolute_uri(reverse("contribute:set_password", args=[
            urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)]))
        messages.success(request, f"{email} can contribute. Send them this link to set their password: {link}")
        return redirect("contribute:people")

    users = (User.objects.filter(Q(groups=group) | Q(contributions__isnull=False)).distinct()
             .annotate(n_done=Count("contributions", filter=~Q(contributions__kind=K.SKIP), distinct=True),
                       n_approved=Count("checked_contributions", filter=Q(checked_contributions__verdict=V.APPROVE), distinct=True),
                       n_checked=Count("checked_contributions", filter=~Q(checked_contributions__verdict=V.NONE), distinct=True))
             .order_by("-n_done"))
    for u in users:
        u.rate = round(100 * u.n_approved / u.n_checked) if u.n_checked else None
        u.last = u.contributions.order_by("-created_at").values_list("created_at", flat=True).first()
    return render(request, "contribute/people.html", {"active": "people", "users": users})

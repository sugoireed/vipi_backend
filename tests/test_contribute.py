import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from apps.contribute.access import GROUP
from apps.contribute.models import Contribution, LexiconWord, SpeechClip

from .test_platform import wav

User = get_user_model()
CLIPS = tempfile.mkdtemp()


@override_settings(TRANSCRIPT_CLIPS_ROOT=CLIPS, ALLOWED_HOSTS=["testserver"], VIPI_ENGINE_URL="")
class ContributeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        folder = Path(CLIPS) / "radio"
        (folder / "ep1").mkdir(parents=True, exist_ok=True)
        rows = []
        for i, conf in enumerate([0.9, 0.4]):
            (folder / f"ep1/t{i}.wav").write_bytes(wav().read())
            rows.append({"audio": f"ep1/t{i}.wav", "start": i * 5.0, "duration": 2.0, "speech": 0.8, "music": 0.1,
                         "source": "sheng_talk", "draft": f"draft {i}", "confidence": conf})
        (folder / "drafts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        group = Group.objects.create(name=GROUP)
        cls.amina, cls.brian = (User.objects.create_user(n, f"{n}@x.ke", "pw-2026-ok!") for n in ("amina", "brian"))
        for u in (cls.amina, cls.brian):
            u.groups.add(group)
        cls.staff = User.objects.create_user("ops", "ops@x.ke", "pw-2026-ok!", is_staff=True)
        cls.outsider = User.objects.create_user("traveller", "t@x.ke", "pw-2026-ok!")
        LexiconWord.objects.create(term="Ambaa", pos="Verb", meanings_en=["Leave"],
                                   examples=[{"text": "Si tuna ambaa", "en": "We're leaving"}])

    def client_for(self, user):
        c = Client()
        c.force_login(user)
        return c

    def test_import_is_idempotent_and_least_confident_draft_comes_first(self):
        call_command("import_clips", "radio", verbosity=0)
        call_command("import_clips", "radio", verbosity=0)
        self.assertEqual(SpeechClip.objects.count(), 2)
        page = self.client_for(self.amina).get("/contribute/transcribe/")
        self.assertContains(page, "draft 1")  # confidence 0.4 before 0.9
        self.assertContains(page, "data:audio/wav;base64,")

    def test_access(self):
        self.assertRedirects(Client().get("/contribute/"), "/contribute/login/?next=/contribute/", fetch_redirect_response=False)
        self.assertEqual(self.client_for(self.outsider).get("/contribute/").status_code, 403)
        self.assertEqual(self.client_for(self.amina).get("/contribute/").status_code, 200)
        self.assertNotEqual(self.client_for(self.amina).get("/contribute/people/").status_code, 200)  # staff only
        self.assertEqual(self.client_for(self.staff).get("/contribute/people/").status_code, 200)

    def test_transcript_needs_a_second_person_and_a_fix_needs_a_third(self):
        call_command("import_clips", "radio", verbosity=0)
        clip = SpeechClip.objects.get(draft="draft 1")
        amina, brian = self.client_for(self.amina), self.client_for(self.brian)
        amina.post(f"/contribute/transcribe/{clip.pk}/", {"action": "save", "text": " niaje  msee "})
        clip.refresh_from_db()
        self.assertEqual((clip.text, clip.transcript_status), ("niaje msee", "submitted"))

        # Amina can't check her own transcript; Brian can, and fixing it makes it his work to be checked again
        self.assertNotContains(amina.get("/contribute/verify/"), "niaje msee")
        brian.post(f"/contribute/verify/{clip.pk}/", {"action": "save", "text": "niaje msee wangu"})
        clip.refresh_from_db()
        self.assertEqual((clip.transcript_status, clip.transcribed_by), ("submitted", self.brian))
        fix = Contribution.objects.get(kind="verify_transcript")
        self.assertEqual((fix.verdict, fix.author), ("fix", self.amina))

        amina.post(f"/contribute/verify/{clip.pk}/", {"action": "save", "text": "niaje msee wangu"})
        clip.refresh_from_db()
        self.assertEqual((clip.transcript_status, clip.transcript_verified_by), ("verified", self.amina))

    def test_back_reopens_your_last_saved_clip_until_someone_else_touches_it(self):
        call_command("import_clips", "radio", verbosity=0)
        first, second = SpeechClip.objects.get(draft="draft 1"), SpeechClip.objects.get(draft="draft 0")
        amina, brian = self.client_for(self.amina), self.client_for(self.brian)
        self.assertNotContains(amina.get("/contribute/transcribe/"), "← Back")  # nothing saved yet
        amina.post(f"/contribute/transcribe/{first.pk}/", {"action": "save", "text": "niaje"})
        amina.post(f"/contribute/transcribe/{second.pk}/", {"action": "save", "text": "poa"})

        # Back walks newest first, and the box holds what she saved, not Riba's draft
        self.assertContains(amina.get("/contribute/transcribe/"), f'href="/contribute/transcribe/{second.pk}/"')
        page = amina.get(f"/contribute/transcribe/{second.pk}/")
        self.assertContains(page, ">poa</textarea>")
        self.assertContains(page, f'href="/contribute/transcribe/{first.pk}/"')
        amina.post(f"/contribute/transcribe/{first.pk}/", {"action": "skip"})  # skip leaves it as it was
        first.refresh_from_db()
        self.assertEqual(first.text, "niaje")
        amina.post(f"/contribute/transcribe/{first.pk}/", {"action": "save", "text": "niaje msee"})
        first.refresh_from_db()
        self.assertEqual((first.text, first.transcript_status), ("niaje msee", "submitted"))

        # once Brian checks it, it's no longer hers to change
        brian.post(f"/contribute/verify/{first.pk}/", {"action": "save", "text": "niaje msee"})
        self.assertEqual(amina.get(f"/contribute/transcribe/{first.pk}/").status_code, 404)
        amina.post(f"/contribute/transcribe/{first.pk}/", {"action": "save", "text": "changed"})
        first.refresh_from_db()
        self.assertEqual(first.text, "niaje msee")

    def test_meaning_flow_and_export(self):
        call_command("import_clips", "radio", verbosity=0)
        clip = SpeechClip.objects.get(draft="draft 0")
        clip.text, clip.transcript_status, clip.transcribed_by = "niaje msee", "verified", self.amina
        clip.save()
        amina, brian = self.client_for(self.amina), self.client_for(self.brian)
        r = amina.post(f"/contribute/meaning/{clip.pk}/", {"action": "save", "en": "hi buddy", "sw": ""})
        self.assertRedirects(r, f"/contribute/meaning/{clip.pk}/", fetch_redirect_response=False)  # both are needed
        amina.post(f"/contribute/meaning/{clip.pk}/", {"action": "save", "en": "hi buddy", "sw": "habari rafiki"})
        # Back reopens it with her meanings in the boxes, until Brian has checked it
        self.assertContains(amina.get("/contribute/meaning/"), f'href="/contribute/meaning/{clip.pk}/"')
        self.assertContains(amina.get(f"/contribute/meaning/{clip.pk}/"), ">habari rafiki</textarea>")
        brian.post(f"/contribute/verify_meaning/{clip.pk}/", {"action": "save", "en": "hi buddy", "sw": "habari rafiki"})
        clip.refresh_from_db()
        self.assertEqual(clip.meaning_status, "verified")
        self.assertEqual(amina.get(f"/contribute/meaning/{clip.pk}/").status_code, 404)

        out = Path(tempfile.mkdtemp())
        call_command("export_contributions", str(out), verbosity=0)
        talk = [json.loads(l) for l in open(out / "data/final/riba/contributed_talk.jsonl")]
        meanings = [json.loads(l) for l in open(out / "data/parallel/contributed_meanings.jsonl")]
        self.assertEqual([t["text"] for t in talk], ["niaje msee"])
        self.assertTrue(Path(talk[0]["audio"]).exists())
        self.assertEqual(meanings[0]["sw"], "habari rafiki")

    def test_meaning_box_starts_with_engine_suggestions_and_never_gemini(self):
        call_command("import_clips", "radio", verbosity=0)
        clip = SpeechClip.objects.get(draft="draft 0")
        clip.text, clip.transcript_status, clip.transcribed_by = "si tuna ambaa", "verified", self.amina
        clip.save()
        answers = {("sheng", "en", "risto"): "we're leaving", ("sw", "en", "mufti"): "we are leaving",
                   ("sheng", "sw", "risto"): None, ("en", "sw", "mufti"): "tunaondoka"}
        calls = []

        def fake(text, source, target, provider):
            calls.append(provider)
            return answers[(source, target, provider)]

        with override_settings(VIPI_ENGINE_URL="http://engine"), mock.patch("apps.contribute.drafts._translate", fake):
            page = self.client_for(self.amina).get("/contribute/meaning/").content.decode()
        self.assertIn(">we&#x27;re leaving</textarea>", page)  # Risto's English first
        self.assertIn(">tunaondoka</textarea>", page)  # Risto copied the Sheng, so Mufti's Swahili
        self.assertIn('data-text="we are leaving"', page)  # Mufti's English offered as the alternative
        self.assertNotIn("gemini", calls)
        clip.refresh_from_db()
        self.assertEqual(clip.meaning_drafts["for"], "si tuna ambaa")

    def test_translate_button_uses_mufti_only(self):
        calls = []

        def fake(text, source, target, provider):
            calls.append((source, target, provider))
            return "tunaondoka" if target == "sw" else "we're leaving"

        amina = self.client_for(self.amina)
        with mock.patch("apps.contribute.drafts._translate", fake):
            self.assertEqual(amina.post("/contribute/translate/", {"text": "we're leaving", "source": "en"}).json(),
                             {"translation": "tunaondoka"})
            self.assertEqual(amina.post("/contribute/translate/", {"text": "tunaondoka", "source": "sw"}).json(),
                             {"translation": "we're leaving"})
            self.assertEqual(amina.post("/contribute/translate/", {"text": "", "source": "en"}).status_code, 400)
        self.assertEqual(calls, [("en", "sw", "mufti"), ("sw", "en", "mufti")])
        self.assertEqual(self.client_for(self.outsider).post("/contribute/translate/", {"text": "x", "source": "en"}).status_code, 403)

    def test_clips_can_be_worked_on_by_category(self):
        call_command("import_clips", "radio", verbosity=0)  # both fixture clips are sheng_talk
        SpeechClip.objects.filter(draft="draft 0").update(source="sheng_radio")
        amina = self.client_for(self.amina)
        page = amina.get("/contribute/transcribe/?source=sheng_radio")
        self.assertContains(page, "draft 0")
        self.assertNotContains(page, "draft 1")
        self.assertContains(amina.get("/contribute/transcribe/"), "draft 0")  # the choice is remembered
        page = amina.get("/contribute/transcribe/?source=sheng_talk")
        self.assertContains(page, "draft 1")
        self.assertContains(page, "Sheng Talk")
        self.assertContains(amina.get("/contribute/transcribe/?source="), "draft")  # back to all
        home = amina.get("/contribute/").content.decode()
        self.assertIn("transcribe/?source=sheng_talk", home)

    def test_word_check_and_skip(self):
        word = LexiconWord.objects.get()
        amina, brian = self.client_for(self.amina), self.client_for(self.brian)
        r = amina.post(f"/contribute/words/{word.pk}/", {"action": "save", "en_ok": "no", "en_correction": ""})
        self.assertRedirects(r, f"/contribute/words/{word.pk}/", fetch_redirect_response=False)  # correction needed
        amina.post(f"/contribute/words/{word.pk}/", {"action": "save", "en_ok": "yes", "sw": "ondoka, toka"})
        word.refresh_from_db()
        self.assertEqual((word.status, word.sw), ("submitted", ["ondoka", "toka"]))
        brian.post(f"/contribute/verify_words/{word.pk}/", {"action": "save", "en_ok": "yes", "sw": "ondoka, toka"})
        word.refresh_from_db()
        self.assertEqual((word.status, word.verified_by), ("verified", self.brian))

        call_command("import_clips", "radio", verbosity=0)
        clip = SpeechClip.objects.get(draft="draft 1")
        brian.post(f"/contribute/transcribe/{clip.pk}/", {"action": "skip"})
        self.assertNotContains(brian.get("/contribute/transcribe/"), "draft 1")  # skipped clips don't come back
        self.assertContains(amina.get("/contribute/transcribe/"), "draft 1")

    def test_only_the_super_admin_skips_the_second_check(self):
        call_command("import_clips", "radio", verbosity=0)
        boss = User.objects.create_superuser("admin@vipi.com", "admin@vipi.com", "pw-2026-ok!")
        clip, other = SpeechClip.objects.get(draft="draft 1"), SpeechClip.objects.get(draft="draft 0")
        self.client_for(boss).post(f"/contribute/transcribe/{clip.pk}/", {"action": "save", "text": "niaje"})
        clip.refresh_from_db()
        self.assertEqual((clip.transcript_status, clip.transcript_verified_by), ("verified", boss))
        self.client_for(self.staff).post(f"/contribute/transcribe/{other.pk}/", {"action": "save", "text": "sasa"})
        other.refresh_from_db()
        self.assertEqual(other.transcript_status, "submitted")  # plain staff still need a second person

        word = LexiconWord.objects.get()
        self.client_for(boss).post(f"/contribute/words/{word.pk}/", {"action": "save", "en_ok": "yes", "sw": "ondoka"})
        word.refresh_from_db()
        self.assertEqual(word.status, "verified")

    def test_invite_link_sets_password_and_logs_in(self):
        staff = self.client_for(self.staff)
        r = staff.post("/contribute/people/", {"name": "Wanjiru K", "email": "Wanjiru@x.ke"}, follow=True)
        link = next(m.message for m in r.context["messages"]).split("password: ")[1]
        user = User.objects.get(username="wanjiru@x.ke")
        self.assertTrue(user.groups.filter(name=GROUP).exists())
        c = Client()
        form = c.get(link.replace("http://testserver", ""), follow=True)
        r = c.post(form.redirect_chain[-1][0], {"new_password1": "mtaani-2026!", "new_password2": "mtaani-2026!"})
        self.assertRedirects(r, "/contribute/", fetch_redirect_response=False)
        self.assertEqual(c.get("/contribute/").status_code, 200)

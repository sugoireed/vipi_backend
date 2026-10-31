"""Radio talk clips are labelled sheng_radio (was ghetto_radio): the source value and the clip folder both change.

The audio files moved from <TRANSCRIPT_CLIPS_ROOT>/ghetto_radio/ to <TRANSCRIPT_CLIPS_ROOT>/sheng_radio/ (moved on
disk separately), so each clip's relative audio path is updated to match.
"""
from django.db import migrations, models
from django.db.models import Value
from django.db.models.functions import Concat, Substr

OLD, NEW = "ghetto_radio", "sheng_radio"


def rename(apps, old, new):
    SpeechClip = apps.get_model("contribute", "SpeechClip")
    SpeechClip.objects.filter(source=old).update(source=new)
    SpeechClip.objects.filter(audio__startswith=f"{old}/").update(
        audio=Concat(Value(f"{new}/"), Substr("audio", len(old) + 2)))


class Migration(migrations.Migration):
    dependencies = [("contribute", "0002_speechclip_meaning_drafts")]

    operations = [
        migrations.AlterField(
            model_name="speechclip", name="source",
            field=models.CharField(db_index=True, help_text="sheng_radio, sheng_talk, …", max_length=30)),
        migrations.RunPython(lambda apps, schema: rename(apps, OLD, NEW),
                             lambda apps, schema: rename(apps, NEW, OLD)),
    ]

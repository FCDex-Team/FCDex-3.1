from django.db import migrations, models


def mascot_to_exclusive(apps, schema_editor):
    PackClaim = apps.get_model("fcdex_3_0", "PackClaim")
    PackClaim.objects.filter(pack_type="mascot").update(pack_type="exclusive")


class Migration(migrations.Migration):
    dependencies = [("fcdex_3_0", "0013_tournament_participation_reward")]

    operations = [
        migrations.RunPython(mascot_to_exclusive, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="packclaim",
            name="pack_type",
            field=models.CharField(
                choices=[("daily", "Daily Pack"), ("weekly", "Weekly Pack"), ("exclusive", "Exclusive Pack")],
                max_length=16,
            ),
        ),
    ]

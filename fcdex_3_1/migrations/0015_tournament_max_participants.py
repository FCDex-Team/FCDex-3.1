from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fcdex_3_0", "0014_pack_type_exclusive")]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="max_participants",
            field=models.PositiveIntegerField(
                default=0, help_text="Maximum total players across both groups. 0 = unlimited."
            ),
        )
    ]

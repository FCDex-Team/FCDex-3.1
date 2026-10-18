from django.db import migrations, models


class Migration(migrations.Migration):
    """Bring the migration state back in line with models.py (metadata only, no data changes)."""

    dependencies = [("fcdex_3_0", "0020_battle_reward_claim")]

    operations = [
        migrations.AlterModelOptions(
            name="playerstats",
            options={"verbose_name": "FCDex 3.1 player stats", "verbose_name_plural": "FCDex 3.1 player stats"},
        ),
        migrations.AlterField(
            model_name="tournament",
            name="max_participants",
            field=models.PositiveIntegerField(
                blank=True, default=0, help_text="Maximum total players across both groups. 0 = unlimited."
            ),
        ),
        migrations.AlterField(
            model_name="tournamentconfig",
            name="id",
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
        ),
        migrations.AlterField(
            model_name="tournamentmatchprize",
            name="round",
            field=models.CharField(
                choices=[
                    ("group", "Group"),
                    ("quarterfinal", "Quarterfinal"),
                    ("semifinal", "Semifinal"),
                    ("final", "Final"),
                ],
                max_length=12,
            ),
        ),
    ]

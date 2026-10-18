import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fcdex_3_0", "0021_sync_model_state")]

    operations = [
        migrations.CreateModel(
            name="SpawnEventConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "twin_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Twin spawn: two clubballs appear side by side and only one of them can be caught.",
                    ),
                ),
                (
                    "twin_chance",
                    models.FloatField(
                        default=10.0,
                        help_text="Percent of natural spawns that become a twin spawn (0-100).",
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "match_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Match spawn: win a match against the spawned clubball to earn a rarer one.",
                    ),
                ),
                (
                    "match_chance",
                    models.FloatField(
                        default=2.0,
                        help_text="Percent of natural spawns that become a match spawn (0-100). "
                        "Keep this low, the prize is rare.",
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "match_difficulty",
                    models.PositiveSmallIntegerField(
                        default=110,
                        help_text="Opponent strength as a percent of the spawned clubball's base stats "
                        "(100 = equal, higher = harder).",
                        validators=[
                            django.core.validators.MinValueValidator(10),
                            django.core.validators.MaxValueValidator(1000),
                        ],
                    ),
                ),
            ],
            options={"verbose_name": "Spawn events config", "verbose_name_plural": "Spawn events config"},
        )
    ]

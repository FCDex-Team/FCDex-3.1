import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        # 0023 is the FC Derby migration (built in parallel), fix the name here if it differs.
        ("fcdex_3_0", "0023_derby"),
        ("bd_models", "0015_alter_ballinstance_server_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PassSeason",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                (
                    "active",
                    models.BooleanField(
                        default=True, help_text="Only one season runs at a time, it ends on its end date."
                    ),
                ),
            ],
            options={
                "verbose_name": "Club pass season",
                "verbose_name_plural": "Club pass seasons",
                "ordering": ("-starts_at",),
            },
        ),
        migrations.AddIndex(
            model_name="passseason",
            index=models.Index(fields=["active", "-starts_at"], name="fcdex_passseason_active_idx"),
        ),
        migrations.CreateModel(
            name="PassLevelReward",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "level",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(50),
                        ]
                    ),
                ),
                (
                    "track",
                    models.CharField(
                        choices=[("normal", "Normal"), ("premium", "Premium")], default="normal", max_length=16
                    ),
                ),
                (
                    "reward_type",
                    models.CharField(
                        choices=[
                            ("none", "Nothing"),
                            ("coins", "Coins"),
                            ("ball", "Specific clubball"),
                            ("random_common", "Random common clubball"),
                        ],
                        default="none",
                        max_length=16,
                    ),
                ),
                ("coins", models.PositiveIntegerField(default=0)),
                ("label", models.CharField(blank=True, default="", max_length=64)),
                (
                    "ball",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "season",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="level_rewards",
                        to="fcdex_3_0.passseason",
                    ),
                ),
            ],
            options={
                "verbose_name": "Club pass level reward",
                "verbose_name_plural": "Club pass level rewards",
                "ordering": ("season", "level", "track"),
            },
        ),
        migrations.AddConstraint(
            model_name="passlevelreward",
            constraint=models.UniqueConstraint(
                fields=("season", "level", "track"), name="fcdex_passreward_unique_level"
            ),
        ),
        migrations.CreateModel(
            name="PassSeasonClub",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "ball",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to="bd_models.ball"
                    ),
                ),
                (
                    "season",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="clubs", to="fcdex_3_0.passseason"
                    ),
                ),
            ],
            options={"verbose_name": "Club pass season club", "verbose_name_plural": "Club pass season clubs"},
        ),
        migrations.AddConstraint(
            model_name="passseasonclub",
            constraint=models.UniqueConstraint(fields=("season", "ball"), name="fcdex_passclub_unique"),
        ),
        migrations.CreateModel(
            name="PlayerPass",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("xp_total", models.PositiveBigIntegerField(default=0)),
                ("premium", models.BooleanField(default=False)),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="club_passes", to="bd_models.player"
                    ),
                ),
                (
                    "season",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="players", to="fcdex_3_0.passseason"
                    ),
                ),
            ],
            options={"verbose_name": "Club pass progress", "verbose_name_plural": "Club pass progress"},
        ),
        migrations.AddConstraint(
            model_name="playerpass",
            constraint=models.UniqueConstraint(fields=("player", "season"), name="fcdex_playerpass_unique"),
        ),
        migrations.CreateModel(
            name="PassRewardClaim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.PositiveSmallIntegerField()),
                ("track", models.CharField(choices=[("normal", "Normal"), ("premium", "Premium")], max_length=16)),
                ("claimed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="club_pass_claims",
                        to="bd_models.player",
                    ),
                ),
                (
                    "season",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="claims", to="fcdex_3_0.passseason"
                    ),
                ),
            ],
            options={"verbose_name": "Club pass reward claim", "verbose_name_plural": "Club pass reward claims"},
        ),
        migrations.AddConstraint(
            model_name="passrewardclaim",
            constraint=models.UniqueConstraint(
                fields=("player", "season", "level", "track"), name="fcdex_passclaim_unique"
            ),
        ),
    ]

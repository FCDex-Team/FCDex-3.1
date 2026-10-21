import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fcdex_3_0", "0022_spawn_event_config"),
        ("bd_models", "0015_alter_ballinstance_server_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DerbyConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "winner_coins_min",
                    models.PositiveIntegerField(default=150, help_text="Fewest coins a derby winner can earn."),
                ),
                (
                    "winner_coins_max",
                    models.PositiveIntegerField(default=300, help_text="Most coins a derby winner can earn."),
                ),
                ("loser_coins", models.PositiveIntegerField(default=50, help_text="Coins the loser gets (0 = none).")),
                (
                    "winner_xp_min",
                    models.PositiveIntegerField(default=20, help_text="Fewest Club Pass XP a derby winner can earn."),
                ),
                (
                    "winner_xp_max",
                    models.PositiveIntegerField(default=30, help_text="Most Club Pass XP a derby winner can earn."),
                ),
                ("loser_xp", models.PositiveIntegerField(default=10, help_text="Club Pass XP the loser gets.")),
                (
                    "daily_limit",
                    models.PositiveSmallIntegerField(
                        default=12,
                        help_text="Derbies each player can play per UTC day.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
            ],
            options={"verbose_name": "Derby config", "verbose_name_plural": "Derby config"},
        ),
        migrations.CreateModel(
            name="DerbyLayout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("formation", models.CharField(default="4-3-3", max_length=16)),
                (
                    "player",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE, related_name="derby_layout", to="bd_models.player"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DerbyStats",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("wins", models.PositiveIntegerField(default=0)),
                ("losses", models.PositiveIntegerField(default=0)),
                ("played", models.PositiveIntegerField(default=0)),
                (
                    "player",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE, related_name="derby_stats", to="bd_models.player"
                    ),
                ),
            ],
            options={"verbose_name": "Derby stats", "verbose_name_plural": "Derby stats"},
        ),
        migrations.CreateModel(
            name="DerbyClaim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("played_at", models.DateTimeField(auto_now_add=True)),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="derby_claims", to="bd_models.player"
                    ),
                ),
            ],
            options={"ordering": ("-played_at",)},
        ),
        migrations.AddIndex(
            model_name="derbyclaim",
            index=models.Index(fields=["player", "-played_at"], name="fcdex_derby_player_played_idx"),
        ),
        migrations.CreateModel(
            name="DerbySlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "position",
                    models.CharField(
                        choices=[("GK", "Goalkeeper"), ("DF", "Defender"), ("MF", "Midfielder"), ("ST", "Striker")],
                        max_length=2,
                    ),
                ),
                ("slot", models.PositiveSmallIntegerField(help_text="0-based slot number inside the position.")),
                (
                    "ball",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to="bd_models.ball"
                    ),
                ),
                (
                    "instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to="bd_models.ballinstance"
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="derby_slots", to="bd_models.player"
                    ),
                ),
            ],
            options={"ordering": ("position", "slot")},
        ),
        migrations.AddConstraint(
            model_name="derbyslot",
            constraint=models.UniqueConstraint(fields=("player", "position", "slot"), name="fcdex_derby_slot_unique"),
        ),
        migrations.AddConstraint(
            model_name="derbyslot",
            constraint=models.UniqueConstraint(fields=("player", "ball"), name="fcdex_derby_ball_unique"),
        ),
    ]

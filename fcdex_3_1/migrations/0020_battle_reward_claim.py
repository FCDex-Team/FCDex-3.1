import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fcdex_3_0", "0019_match_claim"),
        ("bd_models", "0015_alter_ballinstance_server_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BattleRewardClaim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="battle_reward_claims",
                        to="bd_models.player",
                    ),
                ),
            ],
            options={"ordering": ("-granted_at",)},
        ),
        migrations.AddIndex(
            model_name="battlerewardclaim",
            index=models.Index(fields=["player", "-granted_at"], name="fcdex_battlereward_player_idx"),
        ),
    ]

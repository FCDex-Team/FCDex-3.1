import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fcdex_3_0", "0018_sbcrecipe_recipe_type"),
        ("bd_models", "0015_alter_ballinstance_server_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="MatchClaim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("played_at", models.DateTimeField(auto_now_add=True)),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="match_claims", to="bd_models.player"
                    ),
                ),
            ],
            options={"ordering": ("-played_at",)},
        ),
        migrations.AddIndex(
            model_name="matchclaim",
            index=models.Index(fields=["player", "-played_at"], name="fcdex_match_player_played_idx"),
        ),
    ]

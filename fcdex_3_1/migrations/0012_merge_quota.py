import django.db.models.deletion
from django.db import migrations, models


def seed_merge_quota_settings(apps, schema_editor):
    MergeQuotaSettings = apps.get_model("fcdex_3_0", "MergeQuotaSettings")
    MergeQuotaSettings.objects.update_or_create(pk=1, defaults={"weekly_cap": 5, "period_days": 7})


class Migration(migrations.Migration):
    dependencies = [("fcdex_3_0", "0011_quest_definitions")]

    operations = [
        migrations.CreateModel(
            name="MergeQuotaSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "weekly_cap",
                    models.PositiveIntegerField(default=5, help_text="Base merge cap per player per quota period."),
                ),
                (
                    "period_days",
                    models.PositiveSmallIntegerField(
                        default=7, help_text="Quota window length in days. Use 7 for ISO calendar weeks (Monday reset)."
                    ),
                ),
            ],
            options={"verbose_name": "Merge quota settings", "verbose_name_plural": "Merge quota settings"},
        ),
        migrations.CreateModel(
            name="PlayerMergeQuota",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "premium_bonus",
                    models.PositiveIntegerField(
                        default=0, help_text="Extra merges per period on top of the global weekly cap."
                    ),
                ),
                (
                    "cap_override",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text=(
                            "Replace global cap for this player (premium bonus still applies unless you set cap only)."
                        ),
                        null=True,
                    ),
                ),
                (
                    "player",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fcdex_merge_quota",
                        to="bd_models.player",
                    ),
                ),
            ],
            options={"verbose_name": "Player merge quota", "verbose_name_plural": "Player merge quotas"},
        ),
        migrations.RunPython(seed_merge_quota_settings, migrations.RunPython.noop),
    ]

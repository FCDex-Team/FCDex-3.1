from django.contrib import admin

from .models import (
    Achievement,
    MergeLog,
    MergeQuotaSettings,
    PackClaim,
    PlayerAchievement,
    PlayerMergeQuota,
    PlayerQuestProgress,
    PlayerStats,
    QuestDefinition,
    SBCRecipe,
    ShopBundle,
    ShopBundleItem,
    ShopPurchase,
    Tournament,
    TournamentBet,
    TournamentMatch,
    TournamentMatchPrize,
    TournamentParticipantRewardClaim,
    TournamentParticipationReward,
    TournamentRegistration,
)


@admin.register(PlayerStats)
class PlayerStatsAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player",)
    search_fields = ("player__discord_id",)
    list_display = ("player", "battles_won", "battles_played", "merges_completed", "tournament_wins")


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    autocomplete_fields = ("reward_ball",)
    list_display = ("name", "achievement_type", "required_count", "reward_money", "enabled", "hidden")
    list_filter = ("achievement_type", "enabled", "hidden")
    search_fields = ("name", "description")


@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player", "achievement")
    search_fields = ("player__discord_id", "achievement__name")
    list_display = ("player", "achievement", "progress", "unlocked_at", "claimed_at")
    list_filter = ("achievement",)


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    autocomplete_fields = ("host",)
    list_display = (
        "name",
        "status",
        "host",
        "max_participants",
        "betting_enabled",
        "scheduled_start_at",
        "scheduled_end_at",
        "semifinal_cutoff",
        "match_win_reward",
        "created_at",
    )
    list_filter = ("status", "betting_enabled")
    search_fields = ("name", "description", "rules")
    readonly_fields = ("created_at", "started_at", "ended_at")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "description",
                    "rules",
                    "host",
                    "status",
                    "max_participants",
                    "semifinal_cutoff",
                    "match_win_reward",
                )
            },
        ),
        ("Betting", {"fields": ("betting_enabled", "min_bet", "max_bet", "bet_payout_multiplier")}),
        (
            "Schedule",
            {
                "fields": ("scheduled_start_at", "scheduled_end_at", "started_at", "ended_at", "created_at"),
                "description": (
                    "Scheduled start blocks early host starts; registration stays open until the host starts "
                    "group stage or scheduled end passes. Started/ended timestamps are set from "
                    "/tournament manage → Host."
                ),
            },
        ),
    )


@admin.register(TournamentRegistration)
class TournamentRegistrationAdmin(admin.ModelAdmin):
    autocomplete_fields = ("tournament", "player")
    search_fields = ("tournament__name", "player__discord_id", "group")
    list_display = ("tournament", "player", "group", "score", "eliminated", "semifinal_eligible")
    list_filter = ("group", "eliminated", "tournament")


@admin.register(TournamentMatch)
class TournamentMatchAdmin(admin.ModelAdmin):
    autocomplete_fields = ("tournament", "player1", "player2", "winner", "verified_winner")
    search_fields = ("id", "tournament__name", "round", "group")
    list_display = (
        "tournament",
        "round",
        "group",
        "player1",
        "player2",
        "winner",
        "completed",
        "verified_winner",
        "reward_claimed",
    )
    list_filter = ("round", "group", "completed", "tournament")


@admin.register(TournamentMatchPrize)
class TournamentMatchPrizeAdmin(admin.ModelAdmin):
    autocomplete_fields = ("tournament", "match", "ball")
    search_fields = ("label", "tournament__name", "match__id")
    list_display = ("tournament", "match", "round", "group", "prize_type", "coins", "label", "weight")
    list_filter = ("prize_type", "round", "group", "tournament")


@admin.register(TournamentParticipationReward)
class TournamentParticipationRewardAdmin(admin.ModelAdmin):
    autocomplete_fields = ("tournament", "ball")
    search_fields = ("label", "description", "tournament__name")
    list_display = ("tournament", "label", "prize_type", "coins", "ball")
    list_filter = ("prize_type", "tournament")


@admin.register(TournamentParticipantRewardClaim)
class TournamentParticipantRewardClaimAdmin(admin.ModelAdmin):
    autocomplete_fields = ("tournament", "player", "reward")
    search_fields = ("tournament__name", "player__discord_id", "reward__label")
    list_display = ("tournament", "player", "reward", "granted_at")
    list_filter = ("tournament",)
    readonly_fields = ("granted_at",)


@admin.register(TournamentBet)
class TournamentBetAdmin(admin.ModelAdmin):
    autocomplete_fields = ("tournament", "match", "bettor", "picked")
    search_fields = ("tournament__name", "match__id", "bettor__discord_id", "picked__discord_id")
    list_display = ("tournament", "match", "bettor", "picked", "amount", "payout", "resolved", "created_at")
    list_filter = ("resolved", "tournament")


@admin.register(PackClaim)
class PackClaimAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player",)
    list_display = ("player", "pack_type", "claimed_at")
    list_filter = ("pack_type",)


@admin.register(SBCRecipe)
class SBCRecipeAdmin(admin.ModelAdmin):
    autocomplete_fields = ("required_ball", "reward_ball")
    list_display = ("name", "required_ball", "required_count", "reward_ball", "reward_money", "enabled")
    list_filter = ("enabled",)


@admin.register(QuestDefinition)
class QuestDefinitionAdmin(admin.ModelAdmin):
    list_display = ("label", "quest_key", "hook_key", "target", "reward_coins", "enabled", "sort_order")
    list_filter = ("enabled", "hook_key")
    search_fields = ("quest_key", "label", "description")
    ordering = ("sort_order", "quest_key")


@admin.register(PlayerQuestProgress)
class PlayerQuestProgressAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player",)
    list_display = ("player", "quest_key", "day", "progress", "target", "completed_at", "claimed_at")
    list_filter = ("quest_key", "day")


class ShopBundleItemInline(admin.TabularInline):
    model = ShopBundleItem
    autocomplete_fields = ("ball", "special")
    extra = 1


@admin.register(ShopBundle)
class ShopBundleAdmin(admin.ModelAdmin):
    inlines = (ShopBundleItemInline,)
    list_display = ("name", "price", "enabled", "sort_order", "emoji")
    list_filter = ("enabled",)
    search_fields = ("name", "description")
    ordering = ("sort_order", "name")


@admin.register(ShopPurchase)
class ShopPurchaseAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player", "bundle")
    list_display = ("player", "bundle", "purchased_at")
    list_filter = ("bundle",)
    readonly_fields = ("purchased_at",)


@admin.register(MergeLog)
class MergeLogAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player", "source_ball1", "source_ball2", "result_ball")
    search_fields = ("player__discord_id",)
    list_display = ("player", "merge_level", "result_ball", "created_at")
    readonly_fields = ("created_at",)


@admin.register(MergeQuotaSettings)
class MergeQuotaSettingsAdmin(admin.ModelAdmin):
    list_display = ("weekly_cap", "period_days")

    def has_add_permission(self, request):
        return not MergeQuotaSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlayerMergeQuota)
class PlayerMergeQuotaAdmin(admin.ModelAdmin):
    autocomplete_fields = ("player",)
    search_fields = ("player__discord_id",)
    list_display = ("player", "premium_bonus", "cap_override")

from __future__ import annotations

from django.db import models

from bd_models.models import Ball, BallInstance, Player


class TournamentGroup(models.TextChoices):
    LEGACY = "legacy", "Legacy"
    MAIN = "main", "Main"


class TournamentStatus(models.TextChoices):
    REGISTRATION = "registration", "Registration"
    GROUP_STAGE = "group_stage", "Group Stage"
    SEMIFINALS = "semifinals", "Semifinals"
    FINALS = "finals", "Finals"
    COMPLETED = "completed", "Completed"


class TournamentRound(models.TextChoices):
    GROUP = "group", "Group"
    QUARTERFINAL = "quarterfinal", "Quarterfinal"
    SEMIFINAL = "semifinal", "Semifinal"
    FINAL = "final", "Final"


class AchievementType(models.TextChoices):
    BATTLES_WON = "battles_won", "Battles Won"
    MERGES = "merges", "Merges Completed"
    TOURNAMENT_WIN = "tournament_win", "Tournament Wins"
    TOURNAMENT_PARTICIPATE = "tournament_participate", "Tournament Participation"
    BALLS_OWNED = "balls_owned", "Clubballs Owned"
    CUSTOM = "custom", "Custom (manual)"


class PlayerStats(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="fcdex_stats")
    player_id: int
    battles_won = models.PositiveIntegerField(default=0)
    battles_played = models.PositiveIntegerField(default=0)
    merges_completed = models.PositiveIntegerField(default=0)
    tournament_wins = models.PositiveIntegerField(default=0)
    tournament_participations = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "FCDex 3.1 player stats"
        verbose_name_plural = "FCDex 3.1 player stats"

    def __str__(self) -> str:
        return f"Stats for player #{self.player_id}"


class Achievement(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField()
    emoji = models.CharField(max_length=32, default="🏆")
    achievement_type = models.CharField(max_length=32, choices=AchievementType.choices)
    required_count = models.PositiveIntegerField(default=1)
    reward_money = models.PositiveBigIntegerField(default=0)
    reward_ball = models.ForeignKey(Ball, on_delete=models.SET_NULL, null=True, blank=True)
    reward_ball_id: int | None
    hidden = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class PlayerAchievement(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="fcdex_achievements")
    player_id: int
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    progress = models.PositiveIntegerField(default=0)
    unlocked_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("player", "achievement")

    def __str__(self) -> str:
        return f"{self.player_id} - {self.achievement.name}"


class Tournament(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    host = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="hosted_tournaments")
    host_id: int
    status = models.CharField(max_length=16, choices=TournamentStatus.choices, default=TournamentStatus.REGISTRATION)
    semifinal_cutoff = models.PositiveIntegerField(
        default=0, help_text="Minimum group score required to reach semifinals. Lowest scorers are eliminated."
    )
    match_win_reward = models.PositiveIntegerField(
        default=500, help_text="Fallback coins when no bounty pool is configured on the match."
    )
    rules = models.TextField(blank=True, default="", help_text="Tournament rules shown in /tournament view overview.")
    betting_enabled = models.BooleanField(default=True)
    min_bet = models.PositiveIntegerField(default=100)
    max_bet = models.PositiveIntegerField(default=50_000)
    bet_payout_multiplier = models.PositiveSmallIntegerField(
        default=2, help_text="Multiplier applied to winning bets (e.g. 2 = double your wager)."
    )
    max_participants = models.PositiveIntegerField(
        default=0, blank=True, help_text="Maximum total players across both groups. 0 = unlimited."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    scheduled_start_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Planned start — blocks the host from starting group stage early. "
            "Player registration stays open until the host starts or scheduled end passes."
        ),
    )
    scheduled_end_at = models.DateTimeField(
        null=True, blank=True, help_text="Planned end — registration and new match activity close after this time."
    )
    started_at = models.DateTimeField(
        null=True, blank=True, help_text="Actual time the group stage was started via /tournament manage → Host."
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Actual time the tournament was completed via /tournament manage → Host → Advance round.",
    )

    class Meta:
        ordering = ("-created_at",)

    def get_status_display(self) -> str:
        return TournamentStatus(self.status).label

    def __str__(self) -> str:
        return self.name


class TournamentRegistration(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="registrations")
    tournament_id: int
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="tournament_registrations")
    player_id: int
    group = models.CharField(max_length=8, choices=TournamentGroup.choices)
    score = models.IntegerField(default=0)
    eliminated = models.BooleanField(default=False)
    semifinal_eligible = models.BooleanField(default=True)

    class Meta:
        unique_together = ("tournament", "player")

    def __str__(self) -> str:
        return f"{self.player_id} in tournament #{self.tournament_id} ({self.group})"


class TournamentMatch(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="matches")
    tournament_id: int
    round = models.CharField(max_length=12, choices=TournamentRound.choices)
    group = models.CharField(max_length=8, choices=TournamentGroup.choices, null=True, blank=True)
    player1 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="tournament_matches_as_p1")
    player1_id: int
    player2 = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="tournament_matches_as_p2", null=True, blank=True
    )
    player2_id: int | None
    winner = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True, related_name="tournament_wins")
    winner_id: int | None
    score1 = models.IntegerField(default=0)
    score2 = models.IntegerField(default=0)
    completed = models.BooleanField(default=False)
    reward_claimed = models.BooleanField(default=False)
    verified_winner = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_tournament_match_wins",
        help_text="Set when a linked /battle between the two players finishes.",
    )
    verified_winner_id: int | None
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def get_round_display(self) -> str:
        return TournamentRound(self.round).label

    def __str__(self) -> str:
        return f"{self.tournament_id} - {self.round} #{self.pk}"


class TournamentPrizeType(models.TextChoices):
    COINS = "coins", "Coins"
    RANDOM_COMMON = "random_common", "Random Common Clubball"
    BALL = "ball", "Specific Clubball"


class TournamentMatchPrize(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="prizes")
    tournament_id: int
    match = models.ForeignKey(
        TournamentMatch,
        on_delete=models.CASCADE,
        related_name="prizes",
        null=True,
        blank=True,
        help_text="Leave empty to apply this bounty to every match in the round/group.",
    )
    match_id: int | None
    round = models.CharField(max_length=12, choices=TournamentRound.choices)
    group = models.CharField(max_length=8, choices=TournamentGroup.choices, null=True, blank=True)
    prize_type = models.CharField(max_length=16, choices=TournamentPrizeType.choices)
    coins = models.PositiveIntegerField(default=0)
    ball = models.ForeignKey(Ball, on_delete=models.SET_NULL, null=True, blank=True)
    ball_id: int | None
    weight = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ("pk",)

    def get_prize_type_display(self) -> str:
        return TournamentPrizeType(self.prize_type).label

    def __str__(self) -> str:
        target = f"match #{self.match_id}" if self.match_id else f"{self.round}/{self.group or 'all'}"
        return f"{self.tournament_id} · {target} · {self.prize_type}"


class TournamentParticipationReward(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="participation_rewards")
    tournament_id: int
    label = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    prize_type = models.CharField(max_length=16, choices=TournamentPrizeType.choices)
    coins = models.PositiveIntegerField(default=0)
    ball = models.ForeignKey(Ball, on_delete=models.SET_NULL, null=True, blank=True)
    ball_id: int | None

    class Meta:
        ordering = ("pk",)
        verbose_name = "tournament participation reward"
        verbose_name_plural = "tournament participation rewards"

    def get_prize_type_display(self) -> str:
        return TournamentPrizeType(self.prize_type).label

    def __str__(self) -> str:
        return f"Reward #{self.pk} · {self.label or self.get_prize_type_display()}"


class TournamentParticipantRewardClaim(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="participant_claims")
    tournament_id: int
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="participant_reward_claims")
    player_id: int
    reward = models.ForeignKey(TournamentParticipationReward, on_delete=models.CASCADE, related_name="claims")
    reward_id: int
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tournament", "player", "reward")
        ordering = ("-granted_at",)

    def __str__(self) -> str:
        return f"Claim t{self.tournament_id} p{self.player_id} r{self.reward_id}"


class TournamentBet(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="bets")
    tournament_id: int
    match = models.ForeignKey(TournamentMatch, on_delete=models.CASCADE, related_name="bets")
    match_id: int
    bettor = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="tournament_bets")
    bettor_id: int
    picked = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="tournament_bets_picked")
    picked_id: int
    amount = models.PositiveIntegerField()
    payout = models.PositiveIntegerField(default=0)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Bet #{self.pk} · match {self.match_id} · {self.amount} coins"


class TournamentConfig(models.Model):
    """Singleton row (pk=1) for global tournament default caps."""

    max_participants_cap = models.PositiveIntegerField(
        default=0, help_text="Upper limit for tournament max_participants. 0 = unlimited."
    )
    semifinal_cutoff_cap = models.PositiveIntegerField(
        default=0, help_text="Upper limit for tournament semifinal_cutoff. 0 = unlimited."
    )
    min_bet_cap = models.PositiveIntegerField(default=0, help_text="Upper limit for tournament min_bet. 0 = unlimited.")
    max_bet_cap = models.PositiveIntegerField(default=0, help_text="Upper limit for tournament max_bet. 0 = unlimited.")
    bet_payout_multiplier_cap = models.PositiveSmallIntegerField(
        default=0, help_text="Upper limit for tournament bet_payout_multiplier. 0 = unlimited."
    )

    class Meta:
        verbose_name = "Tournament config"
        verbose_name_plural = "Tournament config"

    def __str__(self) -> str:
        return "Tournament config"


class MergeLog(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="merge_logs")
    player_id: int
    source_ball1 = models.ForeignKey(BallInstance, on_delete=models.SET_NULL, null=True, related_name="merge_source1")
    source_ball2 = models.ForeignKey(BallInstance, on_delete=models.SET_NULL, null=True, related_name="merge_source2")
    result_ball = models.ForeignKey(BallInstance, on_delete=models.SET_NULL, null=True, related_name="merge_results")
    merge_level = models.PositiveSmallIntegerField(default=1)
    source_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Merge #{self.pk} by player {self.player_id}"


class MergeQuotaSettings(models.Model):
    """Singleton row (pk=1) for global merge quota defaults."""

    weekly_cap = models.PositiveIntegerField(default=5, help_text="Base merge cap per player per quota period.")
    period_days = models.PositiveSmallIntegerField(
        default=7, help_text="Quota window length in days. Use 7 for ISO calendar weeks (Monday reset)."
    )

    class Meta:
        verbose_name = "Merge quota settings"
        verbose_name_plural = "Merge quota settings"

    def __str__(self) -> str:
        return f"Merge quota · cap {self.weekly_cap} / {self.period_days}d"


class PlayerMergeQuota(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="fcdex_merge_quota")
    player_id: int
    premium_bonus = models.PositiveIntegerField(
        default=0, help_text="Extra merges per period on top of the global weekly cap."
    )
    cap_override = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Replace global cap for this player (premium bonus still applies unless you set cap only).",
    )

    class Meta:
        verbose_name = "Player merge quota"
        verbose_name_plural = "Player merge quotas"

    def __str__(self) -> str:
        return f"Merge quota override · player #{self.player_id}"


class PackType(models.TextChoices):
    DAILY = "daily", "Daily Pack"
    WEEKLY = "weekly", "Weekly Pack"
    EXCLUSIVE = "exclusive", "Exclusive Pack"


class PackClaim(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="pack_claims")
    player_id: int
    pack_type = models.CharField(max_length=16, choices=PackType.choices)
    claimed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-claimed_at",)
        indexes = [models.Index(fields=("player", "pack_type", "-claimed_at"))]

    def __str__(self) -> str:
        return f"{self.player_id} · {self.pack_type}"


class SBCRecipeType(models.TextChoices):
    STANDARD = "standard", "Standard (ball → ball)"
    CLUBBALL_TO_CUSTOM = "clubball_to_custom", "Clubball → Custom"
    CUSTOM_TO_CARD = "custom_to_card", "Custom → Card"


class SBCRecipe(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    recipe_type = models.CharField(max_length=20, choices=SBCRecipeType.choices, default=SBCRecipeType.STANDARD)
    required_ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="sbc_requirements")
    required_ball_id: int
    required_count = models.PositiveSmallIntegerField(default=1)
    reward_ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="sbc_rewards")
    reward_ball_id: int
    reward_money = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "SBC recipe"
        verbose_name_plural = "SBC recipes"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class QuestHook(models.TextChoices):
    PACK_DAILY = "pack_daily", "Open daily pack"
    BATTLE_PLAY = "battle_play", "Play a battle"
    MERGE_ONCE = "merge_once", "Complete a merge"


class QuestDefinition(models.Model):
    quest_key = models.CharField(max_length=32, unique=True, help_text="Unique slug shown in /fcdex quests.")
    label = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    target = models.PositiveIntegerField(default=1)
    reward_coins = models.PositiveIntegerField(default=0)
    hook_key = models.CharField(
        max_length=32,
        choices=QuestHook.choices,
        help_text="Progress hook — must match game events (pack, battle, merge).",
    )
    enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "quest_key")
        verbose_name = "Daily quest definition"
        verbose_name_plural = "Daily quest definitions"

    def __str__(self) -> str:
        return self.label


class PlayerQuestProgress(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="fcdex_quests")
    player_id: int
    quest_key = models.CharField(max_length=32)
    progress = models.PositiveIntegerField(default=0)
    target = models.PositiveIntegerField(default=1)
    completed_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    day = models.DateField()

    class Meta:
        unique_together = ("player", "quest_key", "day")
        ordering = ("-day", "quest_key")

    def __str__(self) -> str:
        return f"{self.player_id} · {self.quest_key} · {self.day}"


class ShopBundle(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    price = models.PositiveIntegerField(help_text="Coin price charged from Player.money")
    enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    emoji = models.CharField(max_length=32, blank=True, default="🛒")

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "Shop bundle"
        verbose_name_plural = "Shop bundles"

    def __str__(self) -> str:
        return self.name


class ShopBundleItem(models.Model):
    bundle = models.ForeignKey(ShopBundle, on_delete=models.CASCADE, related_name="items")
    bundle_id: int
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="shop_bundle_items")
    ball_id: int
    quantity = models.PositiveSmallIntegerField(default=1)
    special = models.ForeignKey(
        "bd_models.Special",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Optional special applied to each granted clubball",
    )
    special_id: int | None

    class Meta:
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"{self.bundle_id} · {self.quantity}× ball #{self.ball_id}"


class ShopPurchase(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="shop_purchases")
    player_id: int
    bundle = models.ForeignKey(ShopBundle, on_delete=models.CASCADE, related_name="purchases")
    bundle_id: int
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-purchased_at",)

    def __str__(self) -> str:
        return f"{self.player_id} bought {self.bundle_id} @ {self.purchased_at}"

from __future__ import annotations

import importlib.util
import sys
from enum import StrEnum
from pathlib import Path
from types import ModuleType, SimpleNamespace

try:
    import discord  # noqa: F401
except ImportError:
    discord_stub = ModuleType("discord")

    class _File:
        def __init__(self, fp, filename: str | None = None) -> None:
            self.fp = fp
            self.filename = filename

    discord_stub.File = _File
    sys.modules["discord"] = discord_stub

import django
from django.conf import settings

ROOT = Path(__file__).resolve().parents[1]


def _install_bd_models_stub() -> None:
    if "bd_models.models" in sys.modules:
        return
    models = ModuleType("bd_models.models")

    class _DoesNotExist(Exception):
        pass

    class _DummyModel:
        DoesNotExist = _DoesNotExist
        objects = SimpleNamespace()

    for name in ("Ball", "BallInstance", "Player", "Special"):
        setattr(models, name, type(name, (_DummyModel,), {"DoesNotExist": _DoesNotExist}))

    models.balls = {}
    models.specials = {}
    pkg = ModuleType("bd_models")
    pkg.models = models
    sys.modules["bd_models"] = pkg
    sys.modules["bd_models.models"] = models


_install_bd_models_stub()


def _install_ballsdex_stub() -> None:
    """Minimal `ballsdex.core.discord` so UI modules import without the host installed.

    The real classes add blacklist checks and tracing on top of discord.py; here they are plain discord.py views.
    """
    try:
        import ballsdex  # noqa: F401

        return
    except ImportError:
        pass
    try:
        import discord.ui as ui
    except ImportError:
        return

    class _AuthorMixin:
        def restrict_author(self, discord_id: int) -> None:
            self.discord_id = discord_id

    class LayoutView(_AuthorMixin, ui.LayoutView):
        pass

    class View(_AuthorMixin, ui.View):
        pass

    class Container(ui.Container):
        pass

    class Modal(ui.Modal):
        pass

    core_discord = ModuleType("ballsdex.core.discord")
    core_discord.LayoutView = LayoutView  # type: ignore[attr-defined]
    core_discord.View = View  # type: ignore[attr-defined]
    core_discord.Container = Container  # type: ignore[attr-defined]
    core_discord.Modal = Modal  # type: ignore[attr-defined]
    core = ModuleType("ballsdex.core")
    core.__path__ = []  # type: ignore[attr-defined]
    core.discord = core_discord  # type: ignore[attr-defined]
    package = ModuleType("ballsdex")
    package.__path__ = []  # type: ignore[attr-defined]
    package.core = core  # type: ignore[attr-defined]
    sys.modules.setdefault("ballsdex", package)
    sys.modules.setdefault("ballsdex.core", core)
    sys.modules.setdefault("ballsdex.core.discord", core_discord)


_install_ballsdex_stub()


def _install_host_settings_stub() -> None:
    """Minimal `settings.models` (the BallsDex settings singleton) for modules that read collectible names."""
    try:
        import settings.models  # noqa: F401

        return
    except ImportError:
        pass

    class _PromptType(StrEnum):
        SPAWN = "spawn"
        CATCH = "catch"
        WRONG = "wrong"
        SLOW = "slow"

    class _PromptMessage:
        PromptType = _PromptType

    class _HostSettings(SimpleNamespace):
        def get_formatted_message(self, *, category, mention, model, bot, **extra) -> str:
            return f"[{category.value}] {mention}"

    host = _HostSettings(
        collectible_name="clubball",
        plural_collectible_name="clubballs",
        currency_name=None,
        currency_plural=None,
        currency_symbol=None,
        currency_symbol_before=False,
        max_attack_bonus=20,
        max_health_bonus=20,
    )
    models = ModuleType("settings.models")
    models.settings = host  # type: ignore[attr-defined]
    models.PromptMessage = _PromptMessage  # type: ignore[attr-defined]
    package = ModuleType("settings")
    package.__path__ = []  # type: ignore[attr-defined]
    package.models = models  # type: ignore[attr-defined]
    sys.modules.setdefault("settings", package)
    sys.modules.setdefault("settings.models", models)


_install_host_settings_stub()


class _TournamentStatus:
    REGISTRATION = "registration"
    GROUP_STAGE = "group_stage"
    SEMIFINALS = "semifinals"
    FINALS = "finals"
    COMPLETED = "completed"


class _TournamentGroup:
    LEGACY = "legacy"
    MAIN = "main"

    def __init__(self, value: str) -> None:
        self.value = value
        self.label = value.title()


class _TournamentRound:
    GROUP = "group"
    QUARTERFINAL = "quarterfinal"
    SEMIFINAL = "semifinal"
    FINAL = "final"


class _TournamentPrizeType:
    COINS = "coins"
    RANDOM_COMMON = "random_common"
    BALL = "ball"


class _FcdexDummyModel:
    objects = SimpleNamespace()


class _PackType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    EXCLUSIVE = "exclusive"


class _AchievementType:
    BATTLES_WON = "battles_won"
    MERGES = "merges"
    TOURNAMENT_WIN = "tournament_win"
    TOURNAMENT_PARTICIPATE = "tournament_participate"
    BALLS_OWNED = "balls_owned"
    CUSTOM = "custom"
    choices = (
        (BATTLES_WON, "Battles Won"),
        (MERGES, "Merges Completed"),
        (TOURNAMENT_WIN, "Tournament Wins"),
        (TOURNAMENT_PARTICIPATE, "Tournament Participation"),
        (BALLS_OWNED, "Clubballs Owned"),
        (CUSTOM, "Custom (manual)"),
    )

    @classmethod
    def __iter__(cls):
        for value, label in cls.choices:
            yield SimpleNamespace(value=value, label=label)


class _QuestHook:
    PACK_DAILY = "pack_daily"
    BATTLE_PLAY = "battle_play"
    MERGE_ONCE = "merge_once"


class _ModelsStub(ModuleType):
    Tournament: type
    TournamentStatus: type[_TournamentStatus]

    def __init__(self) -> None:
        super().__init__("fcdex_3_1.models")
        self.Tournament = object
        self.TournamentStatus = _TournamentStatus
        self.TournamentMatch = object
        self.TournamentRegistration = object
        self.TournamentBet = object
        self.TournamentGroup = _TournamentGroup
        self.TournamentRound = _TournamentRound
        self.TournamentMatchPrize = object
        self.TournamentPrizeType = _TournamentPrizeType
        self.TournamentParticipationReward = _FcdexDummyModel
        self.TournamentParticipantRewardClaim = _FcdexDummyModel
        self.Achievement = object
        self.AchievementType = _AchievementType
        self.PlayerAchievement = object
        self.PlayerStats = object
        self.MergeLog = object
        self.MergeQuotaSettings = object
        self.PlayerMergeQuota = object
        self.PackType = _PackType
        self.PackClaim = object
        self.MatchClaim = object
        self.BattleRewardClaim = object
        self.SpawnEventConfig = object
        self.TournamentConfig = object
        self.QuestDefinition = object
        self.QuestHook = _QuestHook
        self.PlayerQuestProgress = object
        self.SBCRecipe = object
        self.ShopBundle = object
        self.ShopBundleItem = object
        self.ShopPurchase = object


_models_stub = _ModelsStub()
sys.modules.setdefault("fcdex_3_1.models", _models_stub)

if not settings.configured:
    settings.configure(SECRET_KEY="test", USE_TZ=True, TIME_ZONE="UTC", INSTALLED_APPS=[])
    django.setup()

_schedule_path = ROOT / "fcdex_3_1" / "fcdex_ext" / "tournament_schedule.py"
_spec = importlib.util.spec_from_file_location("fcdex_tournament_schedule_test", _schedule_path)
assert _spec and _spec.loader
schedule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schedule)

TournamentStatus = _TournamentStatus


def make_tournament(**kwargs) -> SimpleNamespace:
    defaults: dict = {"status": TournamentStatus.REGISTRATION, "scheduled_start_at": None, "scheduled_end_at": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)

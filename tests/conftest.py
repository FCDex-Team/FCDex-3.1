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
        self.TournamentRound = object
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

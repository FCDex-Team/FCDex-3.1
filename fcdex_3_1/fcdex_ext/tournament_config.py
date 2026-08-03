from __future__ import annotations

from fcdex_3_1.models import TournamentConfig


async def get_tournament_config() -> TournamentConfig:
    """Return the singleton TournamentConfig row, creating it if missing."""
    config, _ = await TournamentConfig.objects.aget_or_create(pk=1)
    return config


def cap_error(value: int, cap: int, label: str) -> str | None:
    """Return an error message if value exceeds the configured cap (cap > 0)."""
    if cap > 0 and value > cap:
        return f"{label} cannot exceed the server cap of **{cap}**."
    return None

from __future__ import annotations

import discord
from discord.components import MediaGalleryItem
from discord.ui import Container, MediaGallery, Separator, TextDisplay

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.pack_assets import pack_art_path
from fcdex_3_1.fcdex_ext.pack_logic import PACK_TYPE_LABELS, PackStatusEntry
from fcdex_3_1.fcdex_ext.views import build_panel_layout, truncate_text


def pack_art_file(pack_type: str) -> discord.File | None:
    path = pack_art_path(pack_type)
    if not path.is_file():
        return None
    return discord.File(str(path), filename=path.name)


def build_pack_open_layout(*, pack_type: str, body: str) -> tuple[LayoutView, list[discord.File]]:
    pack_label = PACK_TYPE_LABELS[pack_type]
    art = pack_art_file(pack_type)
    attachments: list[discord.File] = []

    layout = LayoutView()
    container = Container()
    if art is not None:
        attachments.append(art)
        container.add_item(MediaGallery(MediaGalleryItem(media=f"attachment://{art.filename}", description=pack_label)))
        container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(f"# 📦 {pack_label}\n\n{body}")))
    layout.add_item(container)
    return layout, attachments


def build_pack_menu_layout(entries: list[PackStatusEntry]) -> LayoutView:
    lines: list[str] = []
    for entry in entries:
        command_hint = f" · `{entry.command}`" if entry.command else ""
        lines.append(
            f"{entry.status_emoji} **{entry.label}**\n-# {entry.rewards_summary}\n**{entry.status_text}**{command_hint}"
        )
    return build_panel_layout(
        title="📦 Packs",
        subtitle="Daily · Weekly · Exclusive",
        sections=["\n\n".join(lines)],
        footer="-# Exclusive Pack is granted by admins via `/fcdex admin` → **Packs**",
    )

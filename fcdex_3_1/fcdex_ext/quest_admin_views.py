from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord.ui import ActionRow, Button, Container, Modal, Separator, TextDisplay, TextInput, button

from ballsdex.core.discord import LayoutView
from fcdex_3_1.fcdex_ext.currency import format_money
from fcdex_3_1.fcdex_ext.interaction_context import AdminContext, admin_context
from fcdex_3_1.fcdex_ext.views import AdminHubBackRow, truncate_text
from fcdex_3_1.models import QuestDefinition, QuestHook

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger("fcdex_3_1.quest.admin")

_KEY_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_HOOK_VALUES = {choice.value for choice in QuestHook}


def _normalize_key(raw: str) -> str:
    return raw.strip().lower().replace("-", "_").replace(" ", "_")


class CreateQuestModal(Modal, title="New daily quest"):
    quest_key = TextInput(label="Quest key", placeholder="pack_daily", max_length=32)
    label = TextInput(label="Display name", max_length=128)
    target = TextInput(label="Target count", placeholder="1", max_length=5, default="1")
    reward_coins = TextInput(label="Coin reward", placeholder="500", max_length=12, default="0")
    hook_key = TextInput(
        label="Progress hook", placeholder="pack_daily · battle_play · merge_once", max_length=32, default="pack_daily"
    )

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        key = _normalize_key(self.quest_key.value)
        if not _KEY_RE.fullmatch(key):
            await interaction.response.send_message(
                "Quest key must be 1–32 lowercase letters, numbers, or underscores.", ephemeral=True
            )
            return
        hook = _normalize_key(self.hook_key.value)
        if hook not in _HOOK_VALUES:
            await interaction.response.send_message(
                f"Hook must be one of: {', '.join(sorted(_HOOK_VALUES))}.", ephemeral=True
            )
            return
        try:
            target = int(self.target.value.strip())
            reward = int(self.reward_coins.value.strip().replace(",", ""))
            if target < 1 or reward < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Target must be ≥ 1 and reward must be ≥ 0.", ephemeral=True)
            return
        if await QuestDefinition.objects.filter(quest_key=key).aexists():
            await interaction.response.send_message(f"Quest key **`{key}`** already exists.", ephemeral=True)
            return
        quest = await QuestDefinition.objects.acreate(
            quest_key=key, label=self.label.value.strip(), target=target, reward_coins=reward, hook_key=hook
        )
        ctx = admin_context(interaction)
        layout = await build_quest_admin_layout(
            self.owner_id, ctx, notice=f"Created quest **{quest.label}** (`{quest.quest_key}`)."
        )
        await interaction.response.edit_message(view=layout)


class EditQuestModal(Modal, title="Edit daily quest"):
    label = TextInput(label="Display name", max_length=128)
    target = TextInput(label="Target count", max_length=5)
    reward_coins = TextInput(label="Coin reward", max_length=12)
    description = TextInput(
        label="Description (optional)", required=False, max_length=200, style=discord.TextStyle.paragraph
    )

    def __init__(self, owner_id: int, quest: QuestDefinition):
        super().__init__()
        self.owner_id = owner_id
        self.quest_id = quest.pk
        self.label.default = quest.label
        self.target.default = str(quest.target)
        self.reward_coins.default = str(quest.reward_coins)
        if quest.description:
            self.description.default = quest.description

    async def on_submit(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        try:
            target = int(self.target.value.strip())
            reward = int(self.reward_coins.value.strip().replace(",", ""))
            if target < 1 or reward < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Target must be ≥ 1 and reward must be ≥ 0.", ephemeral=True)
            return
        quest = await QuestDefinition.objects.aget(pk=self.quest_id)
        quest.label = self.label.value.strip()
        quest.target = target
        quest.reward_coins = reward
        quest.description = (self.description.value or "").strip()
        await quest.asave(update_fields=("label", "target", "reward_coins", "description"))
        ctx = admin_context(interaction)
        layout = await build_quest_admin_layout(self.owner_id, ctx, notice=f"Updated **{quest.label}**.")
        await interaction.response.edit_message(view=layout)


class QuestAdminControls(ActionRow):
    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    @button(label="New quest", style=discord.ButtonStyle.success, emoji="➕")
    async def new_quest(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(CreateQuestModal(self.owner_id))

    @button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: Interaction, button: Button):
        ctx = admin_context(interaction)
        layout = await build_quest_admin_layout(self.owner_id, ctx)
        await interaction.response.edit_message(view=layout)


class QuestToggleSelect(discord.ui.Select):
    def __init__(self, owner_id: int, quests: list[QuestDefinition]):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(
                label=q.label[:100],
                value=str(q.pk),
                description=f"{'On' if q.enabled else 'Off'} · {q.hook_key} · target {q.target}"[:100],
            )
            for q in quests[:25]
        ]
        super().__init__(placeholder="Enable / disable quest…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        quest = await QuestDefinition.objects.aget(pk=int(self.values[0]))
        quest.enabled = not quest.enabled
        await quest.asave(update_fields=("enabled",))
        state = "enabled" if quest.enabled else "disabled"
        ctx = admin_context(interaction)
        layout = await build_quest_admin_layout(self.owner_id, ctx, notice=f"**{quest.label}** is now {state}.")
        await interaction.response.edit_message(view=layout)


class QuestEditSelect(discord.ui.Select):
    def __init__(self, owner_id: int, quests: list[QuestDefinition]):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(
                label=q.label[:100],
                value=str(q.pk),
                description=f"`{q.quest_key}` · +{format_money(q.reward_coins)}"[:100],
            )
            for q in quests[:25]
        ]
        super().__init__(placeholder="Edit quest…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel is not yours.", ephemeral=True)
            return
        quest = await QuestDefinition.objects.aget(pk=int(self.values[0]))
        await interaction.response.send_modal(EditQuestModal(self.owner_id, quest))


async def build_quest_admin_layout(owner_id: int, ctx: AdminContext, *, notice: str = "") -> LayoutView:
    quests = [q async for q in QuestDefinition.objects.order_by("sort_order", "quest_key")]
    lines: list[str] = []
    for quest in quests:
        hook_label = QuestHook(quest.hook_key).label
        lines.append(
            f"**{quest.label}** · `{quest.quest_key}`\n"
            f"-# Target **{quest.target}** · **+{format_money(quest.reward_coins)}** · hook **{hook_label}** · "
            f"{'✅' if quest.enabled else '🚫'}"
        )
    body = "\n\n".join(lines) if lines else "*No quests in database — defaults apply until you create one.*"
    if notice:
        body = f"**{notice}**\n\n{body}"

    layout = LayoutView(timeout=600)
    container = Container()
    container.add_item(
        TextDisplay(
            truncate_text(
                "# 📜 Quest admin\n"
                "-# Daily quests for `/fcdex quests` and `/fcdex quest claim`.\n"
                "-# **Hook** must match game events: pack, battle, or merge."
            )
        )
    )
    container.add_item(Separator())
    container.add_item(TextDisplay(truncate_text(body)))
    container.add_item(Separator())
    container.add_item(QuestAdminControls(owner_id))
    if quests:
        toggle_row = ActionRow()
        toggle_row.add_item(QuestToggleSelect(owner_id, quests))
        container.add_item(toggle_row)
        edit_row = ActionRow()
        edit_row.add_item(QuestEditSelect(owner_id, quests))
        container.add_item(edit_row)
    container.add_item(Separator())
    container.add_item(AdminHubBackRow(owner_id))
    layout.add_item(container)
    return layout

# FCDex 3.1 — BallsDex V3 Extra Package

Official **FCDex 3.1** feature pack for [BallsDex V3](https://github.com/Ballsdex-Team/BallsDex-DiscordBot). Packs, SBC crafting, coin shop, guild boss raids, battles, tournaments, quests, and more — Components v2 UI.

Use `/fcdex menu` for the full command directory.

## Features

### 📦 Packs

| Command | Description |
| ------- | ----------- |
| `/pack daily` | **Daily Pack** — 3 clubballs, coins, random ATK/HP % rolls (24h cooldown) |
| `/pack weekly` | **Weekly Pack** — 5 clubballs, coins, stat rolls (7d cooldown) |
| `/fcdex admin` → **Packs** | **Exclusive Pack** (admin-only) — rare clubballs, high stat boosts, specials, large coins |

### 🛒 Shop

Buy admin-configured bundles with **Player coin balance** (enable currency in BallsDex admin Settings).

| Command | Description |
| ------- | ----------- |
| `/fcdex shop` | Browse bundles · purchase via select menu |

Bundle items can grant a clubball **with an optional special** (e.g. Boss). Configure in `/fcdex admin` → Shop or the web panel.

### 🧪 Craft (SBC)

| Command | Description |
| ------- | ----------- |
| `/craft menu` | List active SBC recipes |
| `/craft complete name:<SBC>` | Submit required clubballs and claim the reward |

Admins without a custom admin-panel domain can manage recipes in **`/fcdex admin` → Craft** (Components v2).

### ⚔️ Battles

| Command | Description |
| ------- | ----------- |
| `/battle challenge @user` | Lineup panel (max 5) — **Random 5**, Strongest, Lock |
| `/battle random @user` | Instant random 5v5 (no panel) |
| `/battle all @user` | Uses **every** clubball you own · `skip_commentary:true` for quick results |
| `/battle card` | Add/remove a card from your active lineup |

### 🏟️ Tournaments

Legacy & Main groups · grand final is **Legacy vs Main** semifinal winners.

| Command | Description |
| ------- | ----------- |
| `/tournament view` | Hub — join, leave (while registration open), standings, bracket |
| `/tournament start` | Open group stage (Manage Server) |
| `/tournament match` | Pending matches · **Start battle** · claim |
| `/tournament bet` | Wager on match outcomes |

### ✨ Merge · 🏅 Achievements · 📊 Rarity · 🏆 Leaderboard

- **Merge** — 7-tier forge, same clubball only (`/merge`)
- **Achievements** — `/achievement menu`
- **Rarity** — spawnable, unspawnable, and **specials** (`/fcdex rarity`)
- **Leaderboard** — server vs global (`/fcdex leaderboard`)

### 📋 List regime · 👑 Boss · 📜 Quests

| Command | Description |
| ------- | ----------- |
| `/fcdex list regime:<key>` | Clubballs by regime (UCL, Premier League, etc.) |
| `/fcdex boss` | Guild boss raid — join, pick clubballs, track damage (ephemeral panel) |
| `/fcdex quests` | Daily quest progress |
| `/fcdex quest claim:<key>` | Claim quest coins |

**Boss raids** follow the [BallsDex Boss Pack](https://github.com/MapsDex-Team/BallsDex-Boss-Pack) flow (admin rounds, join button, damage race). Create a **Boss** special in your dex for winner rewards.

### 🛡️ Admin (ephemeral)

| Command | Description |
| ------- | ----------- |
| `/fcdex admin` | Hub — **Shop**, **Craft**, **Quests**, **Boss**, **Owners** (Manage Server) |

All admin panels use Components v2 and reply **ephemeral**.

## Installation

```toml
[[ballsdex.packages]]
location = "git+https://github.com/FCDex-Team/FCDex-3.1.git@3.0.2"
path = "fcdex_3_1"
enabled = true
```

```bash
docker compose build && docker compose up -d
```

### Upgrading

- Set `path = "fcdex_3_1"` and pin the latest tag (e.g. **`@3.0.2`**).
- Run migrations through **`0011`** (configurable daily quests).
- Django app **label stays `fcdex_3_0`** for database compatibility.
- Enable economy: admin **Settings** → set **`currency_name`** (e.g. `coin`).

## Requirements

- BallsDex **V3** (3.0.0+)
- Python **3.12+**

## License

MIT

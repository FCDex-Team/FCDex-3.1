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

The winner of a `/battle challenge` earns a random clubball (no coins), up to **8 rewarded wins per day**.
| `/battle card` | Add/remove a card from your active lineup |

### 🏟️ Tournaments

Legacy & Main groups · grand final is **Legacy vs Main** semifinal winners.

| Command | Description |
| ------- | ----------- |
| `/tournament view` | Hub — join, leave (while registration open), standings, bracket |
| `/tournament start` | Open group stage (Manage Server) |
| `/tournament match` | Pending matches · **Start battle** · claim |
| `/tournament bet` | Wager on match outcomes |

**Join with one tap** — `/tournament manage` → **Announce** posts a public signup message with **Join Legacy**,
**Join Main**, **Leave** and **Details** buttons. Players join without typing a command, and the buttons keep working
after restarts.

### 🎲 Special spawns

Some natural spawns are swapped for a rarer variant. Rates are tuned in `/fcdex admin` → **Spawns** (bot owners) or in
the Django admin under **Spawn events config**.

| Spawn | What happens |
| ----- | ------------ |
| **Twin spawn** | Two clubballs appear side by side. Pick one, name it, and the first correct guess catches that one — the other gets away. |
| **Match spawn** | Rare. Instead of guessing a name, play a match with one of your clubballs. Everyone gets one try, the first win earns a **rarer** clubball than the one shown. |

| Command | Description |
| ------- | ----------- |
| `/fcdex spawn kind:<twin\|match>` | Post one right now to test it (bot owners) |

Catches go through BallsDex's own catch pipeline, so specials, stat bonuses, hooks, events and metrics behave exactly
like a normal catch. Defaults: twin **10%**, match **2%** of natural spawns, match difficulty **110%**.

### 🥅 FC Derby

Build an 11-player squad in a formation and play squad-vs-squad derbies for **coins and Club Pass XP** (no clubballs are
won). Commands live under a top-level `fc` group with a `derby` subgroup.

| Command | Description |
| ------- | ----------- |
| `/fc derby layouts` | Browse formation pictures (4-3-3, 4-4-2, 3-5-2, 4-2-3-1, 5-3-2) · **Next** / **Accept** |
| `/fc derby add position:<GK\|DF\|MF\|ST> clubball:<card> [slot]` | Put a clubball in the first free slot of that position (or replace `slot`). A club can only appear once in your squad |
| `/fc derby remove position slot` | Empty a slot |
| `/fc derby show` | Your squad drawn on the pitch with the clubball pictures |
| `/fc derby status [milestone]` | Derby record and Club Pass level / XP (shows "Club Pass not available" without the Club Pass) |
| `/fc derby challenge challenger:@user` | Both players need a full 11-slot squad. The challenged player accepts, then the match is simulated with commentary |

Rewards (defaults, editable in `/fcdex admin` → **Derby** or the Django admin under **Derby config**): the winner gets
**150-300** coins and **20-30** Club Pass XP, the loser **50** coins and **10** XP. Each player can play **12 derbies per
UTC day** (the challenger and the challenged player both use one), and only one derby can run per player at a time.
`/fcdex leaderboard sort:Derby wins` ranks derby wins.
### 🎟️ Club pass

Seasonal battle-pass: earn xp, level up to **50** and claim coins or clubballs on every reward level.

| Command | Description |
| ------- | ----------- |
| `/club pass` | Season, level, xp bar, rewards per level (paged) · **Claim rewards** takes everything unlocked |
| `/fcdex admin` → **Club Pass** | Start a season (name + months until it ends), set any level reward, add season clubs, grant premium |

- **Seasons** — one at a time, ends on its end date. A new season is seeded with editable defaults: level 1 a random
  common clubball, levels 2-5 nothing, level 6 1,000 coins, then a prize every 5 levels with growing coins, level 50 a
  random common clubball. The **premium** track has the same shape with 3x the coins.
- **Reward types** — nothing, coins, a specific clubball, or a random common clubball. Claims are recorded first (unique
  per player/season/level/track) so double clicks never pay twice.
- **Xp to level up** (per level) — Premium: L1-10 100 · L11-19 250 · L20-29 400 · L30-39 650 · L40-45 900 · L46-49 1,600
  · L50 2,000. Normal: L1-10 350 · L11-29 650 · L30-39 900 · L40-45 1,600 · L46-49 2,100 · L50 2,500.
- **Premium** is a flag an admin sets per player (no payment flow). Premium players use the faster table and can claim
  both tracks.
- **Xp sources** — every catch pays 25 xp (commonest) up to 300 xp (rarest), +50% for the season's clubs (twin and
  match spawn catches included). Other features pay xp through `club_pass_logic.grant_pass_xp(player, amount)`.
  Catch xp uses the `on_ballsdex_ball_caught` event when the host sends it and otherwise a small wrapper around
  `BallSpawnView.catch_ball` (removed on unload, one payment per clubball). A host that has neither pays no catch xp.

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
location = "git+https://github.com/FCDex-Team/FCDex-3.1.git@3.1.7"
path = "fcdex_3_1"
enabled = true
```

```bash
docker compose build && docker compose up -d
```

### Upgrading

- Set `path = "fcdex_3_1"` and pin the latest tag (e.g. **`@3.1.7`**).
- Run migrations through **`0024`**: `0022` special spawn settings, `0023` FC Derby, `0024` Club Pass. `0021` only
  syncs migration metadata.
- Django app **label stays `fcdex_3_0`** for database compatibility.
- Enable economy: admin **Settings** → set **`currency_name`** (e.g. `coin`). Amounts follow your currency name,
  plural, symbol and emoji settings.

## Requirements

- BallsDex **V3** (3.0.0+). Checked against **3.1.0**, **3.2.0** and the current `v3` branch.
- Python **3.12+**

On BallsDex builds that have the events and hooks API (newer than 3.2.0), FCDex honours other packages' `spawn_check`
and `pre_catch` hooks and announces its spawns and catches through the standard events. Older builds work too, those
extras are simply skipped.

## License

MIT

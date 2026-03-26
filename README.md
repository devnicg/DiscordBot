# CongoBot

A Discord bot for the Congo RP community that manages member onboarding and embassy access, integrated with the [WarEra.io](https://warera.io) game.

---

## What It Does

### Member Onboarding

When a new member joins the server, CongoBot opens a private onboarding channel and guides them through one of three paths:

| Path | Who it's for | What happens |
|---|---|---|
| **Visitor** | Anyone exploring | Assigns the Visitor role after confirming their WarEra identity |
| **Citizen** | Congo citizens in WarEra | Assigns the Citizen role after verifying citizenship via a company rename token |
| **Embassy** | Foreign government officials | Sets up an embassy channel for their country and assigns appropriate access |

Identity is verified by asking the user to **rename one of their WarEra companies** to a randomly generated token. The bot polls WarEra's API every minute to check for the rename, then automatically completes the flow once confirmed.

### Embassy System

Each country gets a dedicated embassy channel with two permission tiers:

- **Read access** (`Embassy {Country} {Flag}` role) — all members of that country's embassy
- **Write access** (`Embassy {Country} {Flag} - Officials` role) — government officials (President, Vice President, Minister of Foreign Affairs)

Embassy roles are **colored to match the country's flag** and are **hoisted** so members appear in their own section of the member list.

Officials with write access can grant write permissions to other embassy members using `/addwrite`. Write grants are tracked and automatically revoked if the granting official loses their government role.

### Automated Role Auditing

Every day at **07:00 UTC**, the bot cross-references all tracked members against WarEra's live data:

- Citizens who lost Congo citizenship are downgraded to Visitor
- Visitors who gained a government role are notified via DM
- Embassy officials who lost their government role are downgraded to Visitor
- Embassy officials who changed country are automatically moved to the new country's embassy
- Write grants made by demoted officials are cascade-revoked (grantees are notified via DM)

### Inactivity Management

- After **7 days** of no activity in an onboarding channel, the user is warned in the channel
- After **14 days**, the user is kicked from the server and the channel is deleted

### Automatic Backups

The database is backed up automatically every hour to `data/congobot.db.bak`. You can also trigger a manual backup at any time with `/backup-db`.

---

## Commands

### User Commands

| Command | Description |
|---|---|
| `/reset-request` | Deletes your current onboarding channel and immediately starts a new one |
| `/retry-application` | Re-pings your country's officials if your embassy request is still pending approval |

### Admin / Senate Commands

| Command | Description |
|---|---|
| `/setup` | Interactive 5-step wizard to configure the bot (categories and roles) |
| `/config` | Displays the current configuration with `.env`-ready values to copy |
| `/test-onboarding` | Simulates a member join for a given user (opens their onboarding channel) |
| `/test-visitor` | Instantly completes the visitor flow for a user in an active onboarding channel |
| `/test-citizen` | Instantly completes the citizen flow (skips WarEra country check) |
| `/test-embassy` | Instantly completes the embassy flow |
| `/addwrite` | Grants write access in the current embassy channel — Pres, VP, or MoFA only |
| `/admin-restore` | Manually adds a Discord member into the database without re-running onboarding — use after a DB reset to restore visitors, citizens, or embassy members |
| `/admin-restore-write` | Restores a write grant between two embassy members after a database reset |
| `/admin-db-status` | Lists all tracked members and cross-checks their Discord roles against the database |
| `/backup-db` | Forces an immediate database backup |

---

## Setup

### Prerequisites

- A Discord bot application with a token ([Discord Developer Portal](https://discord.com/developers/applications))
- Docker and Docker Compose installed on your server
- The bot invited to your server with the following permissions:
  - Manage Channels
  - Manage Roles
  - Kick Members
  - Send Messages
  - Read Message History

> **Privileged Intents:** Enable **Server Members Intent** and **Message Content Intent** in the Discord Developer Portal under your bot's settings.

---

### 1. Clone the Repository

```bash
git clone <repo-url>
cd CongoBot
```

### 2. Create the `.env` File

Copy the example below and fill in your values:

```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_guild_id_here
```

You can optionally override the database path (defaults to `data/congobot.db`):

```env
DB_PATH=data/congobot.db
```

You can also pre-seed the bot configuration via environment variables (used as fallback values if the database is ever lost):

```env
SETUP_ONBOARDING_CATEGORY_ID=
SETUP_EMBASSY_CATEGORY_ID=
SETUP_SENATE_ROLE_ID=
SETUP_VISITOR_ROLE_ID=
SETUP_CITIZEN_ROLE_ID=
```

> **Note:** All of these can be configured interactively using `/setup` after the bot is running. The env vars are only used as a recovery fallback — they never overwrite values already in the database.

---

### 3. Start the Bot

```bash
docker compose up -d --build
```

The bot will start and connect to Discord. The SQLite database is stored at **`./data/congobot.db`** — a plain file you can copy and back up. It persists across restarts and rebuilds as long as the file is not deleted.

To view logs:
```bash
docker compose logs -f
```

To stop the bot:
```bash
docker compose down
```

---

### 4. Run `/setup` in Discord

Once the bot is online, run `/setup` in your server (requires Administrator permission). The wizard walks you through 5 steps:

1. **Onboarding category** — where private onboarding channels are created
2. **Embassy category** — where embassy channels are created
3. **Senate role** — members with this role can run admin/senate commands
4. **Visitor role** — assigned to verified visitors (can create a new one)
5. **Citizen role** — assigned to verified Congo citizens (can create a new one)

After completing `/setup`, the bot is fully operational.

> **Important:** Run `/config` immediately after `/setup` and copy the output into your `.env` file. These values act as a fallback — if `data/congobot.db` is ever lost, the bot restores its configuration automatically on the next restart without needing `/setup` again.

---

### Updating

To pull the latest changes and restart:

```bash
git pull
docker compose up -d --build
```

The database is unaffected by rebuilds.

---

### Recovering from a Lost Database

If `data/congobot.db` is lost or corrupted, the bot recreates an empty database on the next start. Bot configuration is restored automatically from the `.env` fallback values. Member data must be re-entered manually using the admin restore commands:

1. **`/admin-restore`** — re-adds each member (visitor, citizen, or embassy official) with their WarEra ID. This re-assigns their Discord role and recreates embassy channels/roles as needed.
2. **`/admin-restore-write`** — re-creates write grants inside embassy channels.
3. **`/admin-db-status`** — confirms all entries are correct and that every member's Discord role is still in sync.

---

### Backing Up the Database

The bot automatically backs up the database to `./data/congobot.db.bak` every hour. You can also trigger a manual backup with `/backup-db` at any time.

To manually copy the backup:
```bash
cp data/congobot.db data/congobot.db.bak
```

---

### Removing the Bot

To stop the bot and delete all data:

```bash
docker compose down
rm data/congobot.db data/congobot.db.bak
```

To stop without deleting data:

```bash
docker compose down
```

---
### Author

Liquidos

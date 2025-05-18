# 🏰 Age of Empires IV Discord Bot

A comprehensive Discord bot for Age of Empires IV communities. This bot tracks player ranks, displays live games, maintains leaderboards, and automatically fetches and posts official AoE4 news and patch notes.

---

## ✨ Features

- **Player Registration System:** Register your main and smurf accounts, linking Discord users to AoE4 in-game profiles
- **Automatic Rank Tracking:** Fetches player data from aoe4world.com API and updates Discord roles automatically
- **Live Game Tracker:** Shows real-time information about community members currently in games
- **Recent Match Tracking:** Displays recently completed matches with results and statistics
- **Leaderboards:** Auto-updating solo and team leaderboards with custom Discord embeds
- **News Integration:** Automatically scrapes and posts official AoE4 news and patch notes
- **Role Management:** Assigns and updates rank roles based on in-game ranks

---

## 🔧 Requirements

- Python 3.8+
- `discord.py`
- `aiohttp`
- `beautifulsoup4`
- `sqlite3`
- A Discord bot token with proper permissions

---

## 📥 Installation

Clone this repository:

```bash
git clone https://github.com/yourusername/aoe4-discord-bot.git
cd aoe4-discord-bot
```

Install required packages:

```bash
pip install -r requirements.txt
```

Configure the bot:

- Replace channel IDs and role IDs in `config.py` with your own
- Set your bot token in the `.env` file or directly in `main.py`

Run the bot:

```bash
python main.py
```

---

## ⚙️ Configuration

Before running the bot, you must configure the following in `config.py`:

- `RANK_CHANNEL_ID` - Channel for rank-related messages
- `LOG_CHANNEL_ID` - Channel for logging bot activities
- `LEADERBOARD_CHANNEL_ID` - Channel for leaderboard displays
- `ACTIVE_PLAYERS_CHANNEL_ID` - Channel for live game tracking
- `PATCH_NOTES_CHANNEL_ID` - Channel for news and patch notes
- `RANK_ROLES` - Dictionary mapping rank tiers to role IDs in your server

---

## 🤖 Commands

| Command | Description |
|---------|-------------|
| `/register @user <ingame_id> <main/smurf>` | Register a player with their AoE4 ID |
| `/leaderboard` | Update and display the leaderboards |
| `/stats [@user]` | Show detailed stats for yourself or mentioned user |
| `/delete [@user]` | Delete player data (admin only or self) |
| `/showall` | List all registered players |
| `/forcenewscheck [patch/announcement/both]` | Force check for new AoE4 news (admin) |

---

## 🔄 Automated Features

The bot runs several background tasks:

- **Daily Player Updates (24h):** Updates all player data and leaderboards
- **Live Game Tracking (30s):** Checks for players in active games
- **News Monitoring (4h):** Checks for new AoE4 news and patch notes
- **News Cleanup (12h):** Verifies and cleans up any deleted news posts

---

## 📁 Project Structure

```
aoe4-discord-bot/
├── main.py              # Bot initialization and event handlers
├── config.py            # Configuration constants and settings
├── database.py          # Database operations and setup
├── commands.py          # Bot command implementations
├── tasks.py             # Background tasks
├── utils.py             # Utility functions
├── news.py              # News fetching and processing
├── requirements.txt     # Dependencies
├── .env                 # Environment variables (create this file)
└── README.md            # This documentation
```

---

## 🗃️ Database Structure

The bot uses SQLite with the following tables:

- **players** - Stores player information and ranks
- **bot_state** - Persists bot state between restarts
- **aoe4_news** - Tracks posted news articles to prevent duplicates

---

## 🔎 Customizing Rank Roles

To customize the rank roles, modify the `RANK_ROLES` dictionary in `config.py`:

```python
RANK_ROLES = {
    "unranked": YOUR_UNRANKED_ROLE_ID,
    "bronze": YOUR_BRONZE_ROLE_ID,
    "silver": YOUR_SILVER_ROLE_ID,
    "gold": YOUR_GOLD_ROLE_ID,
    "platinum": YOUR_PLATINUM_ROLE_ID,
    "diamond": YOUR_DIAMOND_ROLE_ID,
    "conqueror": YOUR_CONQUEROR_ROLE_ID
}
```

---

## ⚠️ Important Notes

- The bot requires the `members` and `message_content` intents
- Ensure your bot has permissions to manage roles if using the automatic role assignment
- The default update frequency is set for a medium-sized community (100 actif member); adjust as needed
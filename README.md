# 🎵 Telegram VC Music Bot v3

Stream music into Telegram voice chats with a persistent queue, lyrics, radio mode, and democratic skipping.

## What's new in v3

| Feature | v2 | v3 |
|---|---|---|
| 📝 `/lyrics` | ❌ | ✅ auto-fetched, chunked for long songs |
| 📻 `/radio <genre>` | ❌ | ✅ 16 genres, endless auto-refill |
| 🗳️ `/voteskip` | ❌ | ✅ configurable threshold |
| 📜 `/history` | ❌ | ✅ last 20 played per group |
| 🗄️ SQLite persistence | ❌ | ✅ queue + settings survive restarts |
| ♻️ Auto-resume on restart | ❌ | ✅ notifies groups to resume |
| 🔁 Stale URL retry | ❌ | ✅ re-fetches expired yt-dlp URLs |
| 📋 Rotating log file | ❌ | ✅ `logs/bot.log` (5 MB × 3) |
| 📻 Radio auto-refill | ❌ | ✅ tops up when queue runs low |

---

## File layout

```
music_bot_v3/
├── bot.py          # entry point
├── config.py       # all settings
├── commands.py     # all /command handlers + callbacks
├── player.py       # playback engine
├── state.py        # in-memory per-chat state
├── database.py     # SQLite persistence (aiosqlite)
├── lyrics.py       # lyrics fetcher (lyrics.ovh + lrclib.net)
├── radio.py        # genre radio seeding via yt-dlp
├── voteskip.py     # vote-skip logic
├── keyboards.py    # inline button layouts
├── helpers.py      # yt-dlp, Spotify, admin check, formatting
├── gen_session.py  # run once to get SESSION_STRING
├── requirements.txt
└── .env.example
data/
└── musicbot.db     # auto-created on first run
logs/
└── bot.log         # rotating log
```

---

## Setup

### 1. Install

```bash
pip install -r requirements.txt
# Optional Spotify support:
pip install spotipy
```

ffmpeg is required: `sudo apt install ffmpeg` / `brew install ffmpeg`

### 2. Configure

```bash
cp .env.example .env
# fill in API_ID, API_HASH, BOT_TOKEN, SESSION_STRING
```

Generate your session string (once):
```bash
python gen_session.py
```

### 3. Run

```bash
python bot.py
```

---

## Commands

| Command | Description | Admin? |
|---|---|---|
| `/play <song/URL>` | Search & play, or add to queue | No |
| `/radio <genre>` | Start endless genre radio | No |
| `/lyrics [song]` | Fetch lyrics for current or named track | No |
| `/history` | Show last 20 played tracks | No |
| `/voteskip` | Vote to skip (majority needed) | No |
| `/np` | Now playing + inline controls | No |
| `/queue` | Show queue | No |
| `/pause` / `/resume` | Pause / resume | No |
| `/vol 0–200` | Set volume | No |
| `/loop` | Toggle loop mode | No |
| `/skip` | Skip (instant) | ✅ |
| `/stop` | Stop & clear queue | ✅ |

---

## Radio genres

`lofi` · `hiphop` · `pop` · `rock` · `electronic` · `jazz` · `classical` · `rnb` · `metal` · `country` · `reggae` · `kpop` · `anime` · `gaming` · `sleep` · `workout`

Custom genres also work: `/radio synthwave`

---

## Key config options (`config.py`)

```python
ADMIN_ONLY_CMDS  = True    # /skip and /stop require admin
VOTESKIP_THRESHOLD = 0.5   # fraction of members to pass a vote-skip
RADIO_AUTO_REFILL  = True  # add more tracks when queue runs low
RADIO_REFILL_AT    = 3     # refill when fewer than this many tracks remain
AUTO_RESUME        = True  # restore queues after restart
HISTORY_LIMIT      = 20    # tracks shown in /history
```

---

## Systemd deployment

```ini
[Unit]
Description=Telegram Music Bot v3
After=network.target

[Service]
WorkingDirectory=/path/to/music_bot_v3
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now musicbot
```

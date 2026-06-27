"""
config.py — All bot settings.
"""

import os
import base64
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
API_ID         = int(os.environ["API_ID"])
API_HASH       = os.environ["API_HASH"]
BOT_TOKEN      = os.environ["BOT_TOKEN"]
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()

# ── YouTube Cookies ───────────────────────────────────────────────────────────
# See cookies/HOW_TO_GET_COOKIES.md
YT_COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "cookies/youtube.txt")

# Railway-friendly cookies support. Set either:
#   YT_COOKIES_CONTENT = raw Netscape cookies.txt content
#   YT_COOKIES_B64     = base64 encoded cookies.txt content
def _write_youtube_cookies_from_env():
    raw = os.getenv("YT_COOKIES_CONTENT", "").strip()
    b64 = os.getenv("YT_COOKIES_B64", "").strip()
    if not raw and not b64:
        return
    try:
        content = base64.b64decode(b64).decode("utf-8") if b64 else raw.replace("\\n", "\n")
        path = Path(YT_COOKIES_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception:
        # Avoid printing cookie content by accident. yt-dlp will show a normal error if unusable.
        pass


_write_youtube_cookies_from_env()

# ── Behaviour ─────────────────────────────────────────────────────────────────
DEFAULT_VOLUME   = int(os.getenv("DEFAULT_VOLUME", "100"))
MAX_QUEUE_SIZE   = int(os.getenv("MAX_QUEUE_SIZE", "50"))
ADMIN_ONLY_CMDS  = os.getenv("ADMIN_ONLY_CMDS", "true").lower() in ("1", "true", "yes", "on")
LOG_CHANNEL_ID   = int(os.getenv("LOG_CHANNEL_ID", "0"))
OWNER_ID         = int(os.getenv("OWNER_ID", "8708907310"))
OWNER_PHONE      = os.getenv("OWNER_PHONE", "8708907310")

# ── Vote-skip ─────────────────────────────────────────────────────────────────
VOTESKIP_THRESHOLD = 0.5

# ── Radio ─────────────────────────────────────────────────────────────────────
RADIO_AUTO_REFILL    = os.getenv("RADIO_AUTO_REFILL", "true").lower() in ("1", "true", "yes", "on")
RADIO_REFILL_AT      = int(os.getenv("RADIO_REFILL_AT", "3"))
RADIO_PREFER_SPOTIFY = os.getenv("RADIO_PREFER_SPOTIFY", "true").lower() in ("1", "true", "yes", "on")
PREFER_SPOTIFY_SEARCH = os.getenv("PREFER_SPOTIFY_SEARCH", "true").lower() in ("1", "true", "yes", "on")

# Spotify curated playlist IDs for each genre (public playlists, no login needed)
SPOTIFY_GENRE_PLAYLISTS: dict[str, str] = {
    "lofi":       "https://open.spotify.com/playlist/0vvXsWCC9xrXsKd4eEHFjV",
    "hiphop":     "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd",
    "pop":        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    "rock":       "https://open.spotify.com/playlist/37i9dQZF1DWXRqgorJj26U",
    "electronic": "https://open.spotify.com/playlist/37i9dQZF1DX4dyzvuaRJ0n",
    "jazz":       "https://open.spotify.com/playlist/37i9dQZF1DXbITWG1ZJKYt",
    "classical":  "https://open.spotify.com/playlist/37i9dQZF1DWWEJlAGA9gs0",
    "rnb":        "https://open.spotify.com/playlist/37i9dQZF1DX4SBhb3fqCJd",
    "metal":      "https://open.spotify.com/playlist/37i9dQZF1DWTcqUzwhNmKv",
    "country":    "https://open.spotify.com/playlist/37i9dQZF1DX1lVhptIYRda",
    "kpop":       "https://open.spotify.com/playlist/37i9dQZF1DX9tPFAsjUPMK",
    "anime":      "https://open.spotify.com/playlist/37i9dQZF1DWT8aqnwgRt92",
    "workout":    "https://open.spotify.com/playlist/37i9dQZF1DX76Wlfdnj7AP",
    "sleep":      "https://open.spotify.com/playlist/37i9dQZF1DWZd79rJ6a7lp",
    "bollywood":  "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd",  # swap with real Bollywood playlist
    "punjabi":    "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd",  # swap with real Punjabi playlist
}

# ── Persistence ───────────────────────────────────────────────────────────────
AUTO_RESUME   = os.getenv("AUTO_RESUME", "true").lower() in ("1", "true", "yes", "on")
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "20"))

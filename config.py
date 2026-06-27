"""
config.py — All bot settings.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ─────────────────────────────────────────────────────────────────
API_ID         = int(os.environ["API_ID"])
API_HASH       = os.environ["API_HASH"]
BOT_TOKEN      = os.environ["BOT_TOKEN"]
SESSION_STRING = os.environ["SESSION_STRING"]

# ── Spotify (Required for Spotify radio/play) ────────────────────────────────
# Get from: https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# ── YouTube Cookies (IMPORTANT — bypass bot detection & age restriction) ─────
# Export cookies from your browser using the "Get cookies.txt LOCALLY" extension
# Place the file at: cookies/youtube.txt
# Supported formats: Netscape cookies.txt (works with yt-dlp directly)
YT_COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "cookies/youtube.txt")

# ── Behaviour ─────────────────────────────────────────────────────────────────
DEFAULT_VOLUME   = 100
MAX_QUEUE_SIZE   = 50
ADMIN_ONLY_CMDS  = True
LOG_CHANNEL_ID   = int(os.getenv("LOG_CHANNEL_ID", "0"))

# ── Vote-skip ─────────────────────────────────────────────────────────────────
VOTESKIP_THRESHOLD = 0.5

# ── Radio ─────────────────────────────────────────────────────────────────────
RADIO_AUTO_REFILL    = True
RADIO_REFILL_AT      = 3
# Prefer Spotify playlists for radio if credentials are set
RADIO_PREFER_SPOTIFY = True
# Public Spotify playlist IDs per genre (curated)
SPOTIFY_GENRE_PLAYLISTS: dict[str, str] = {
    "lofi":       "0vvXsWCC9xrXsKd4eEHFjV",  # Lo-Fi Beats
    "hiphop":     "37i9dQZF1DX0XUsuxWHRQd",  # RapCaviar
    "pop":        "37i9dQZF1DXcBWIGoYBM5M",  # Today's Top Hits
    "rock":       "37i9dQZF1DWXRqgorJj26U",  # Rock Classics
    "electronic": "37i9dQZF1DX4dyzvuaRJ0n",  # Mint (electronic)
    "jazz":       "37i9dQZF1DXbITWG1ZJKYt",  # Jazz Classics
    "classical":  "37i9dQZF1DWWEJlAGA9gs0",  # Classical Essentials
    "rnb":        "37i9dQZF1DX4SBhb3fqCJd",  # Are & Be
    "metal":      "37i9dQZF1DWTcqUzwhNmKv",  # Metal Essentials
    "country":    "37i9dQZF1DX1lVhptIYRda",  # Hot Country
    "kpop":       "37i9dQZF1DX9tPFAsjUPMK",  # K-Pop Daebak
    "anime":      "37i9dQZF1DWT8aqnwgRt92",  # Anime Hits
    "workout":    "37i9dQZF1DX76Wlfdnj7AP",  # Beast Mode
    "sleep":      "37i9dQZF1DWZd79rJ6a7lp",  # Sleep
}

# ── Persistence ───────────────────────────────────────────────────────────────
AUTO_RESUME   = True
HISTORY_LIMIT = 20

"""
helpers.py — Audio resolution, admin check, formatting utilities.
"""

import asyncio
import re
import time
from typing import Optional
import yt_dlp

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        _sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
            )
        )
        SPOTIFY_ENABLED = True
    else:
        SPOTIFY_ENABLED = False
        _sp = None
except ImportError:
    SPOTIFY_ENABLED = False
    _sp = None

# ── Regex ────────────────────────────────────────────────────────────────────
SPOTIFY_TRACK_RE    = re.compile(r"spotify\.com/track/([A-Za-z0-9]+)")
SPOTIFY_PLAYLIST_RE = re.compile(r"spotify\.com/playlist/([A-Za-z0-9]+)")
SPOTIFY_ALBUM_RE    = re.compile(r"spotify\.com/album/([A-Za-z0-9]+)")


# ── Spotify helpers ───────────────────────────────────────────────────────────

def _spotify_track_to_query(track_id: str) -> list[str]:
    """Return ['Artist - Title'] for a single Spotify track."""
    t = _sp.track(track_id)
    artist = t["artists"][0]["name"]
    name   = t["name"]
    return [f"{artist} - {name}"]


def _spotify_playlist_to_queries(playlist_id: str) -> list[str]:
    results = _sp.playlist_items(playlist_id, additional_types=("track",))
    queries = []
    while results:
        for item in results["items"]:
            t = item.get("track")
            if t:
                artist = t["artists"][0]["name"]
                queries.append(f"{artist} - {t['name']}")
        results = _sp.next(results) if results["next"] else None
    return queries[:50]  # cap at 50


def _spotify_album_to_queries(album_id: str) -> list[str]:
    results = _sp.album_tracks(album_id)
    queries = []
    album   = _sp.album(album_id)
    artist  = album["artists"][0]["name"]
    for t in results["items"]:
        queries.append(f"{artist} - {t['name']}")
    return queries


def resolve_spotify(url: str) -> list[str]:
    """
    Given a Spotify URL, return a list of 'Artist - Title' search queries.
    Returns [] if Spotify support is not enabled.
    """
    if not SPOTIFY_ENABLED or not _sp:
        return []
    m = SPOTIFY_TRACK_RE.search(url)
    if m:
        return _spotify_track_to_query(m.group(1))
    m = SPOTIFY_PLAYLIST_RE.search(url)
    if m:
        return _spotify_playlist_to_queries(m.group(1))
    m = SPOTIFY_ALBUM_RE.search(url)
    if m:
        return _spotify_album_to_queries(m.group(1))
    return []


# ── YouTube / yt-dlp ─────────────────────────────────────────────────────────

_YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "default_search": "ytsearch1",
    "socket_timeout": 15,
}


def _ydl_extract(query: str) -> dict:
    with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info


async def get_track_info(query: str) -> dict:
    """
    Resolve any query (YT URL, YT search, Spotify URL) to a track dict:
      { title, url, duration, thumbnail, webpage_url }

    For Spotify URLs returns the first resolved track; use resolve_spotify()
    for full playlist handling.
    """
    # Spotify single track fast path
    if "spotify.com" in query and SPOTIFY_ENABLED:
        queries = resolve_spotify(query)
        if queries:
            query = queries[0]

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _ydl_extract, query)
    return {
        "title":       info.get("title", "Unknown"),
        "url":         info["url"],
        "duration":    info.get("duration", 0),
        "thumbnail":   info.get("thumbnail", ""),
        "webpage_url": info.get("webpage_url", ""),
    }


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_duration(seconds: int) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def progress_bar(elapsed: float, total: float, width: int = 12) -> str:
    if total <= 0:
        return "─" * width
    filled = int(width * elapsed / total)
    filled = min(filled, width)
    bar = "▓" * filled + "░" * (width - filled)
    return bar


# ── Admin check ───────────────────────────────────────────────────────────────

async def is_admin(client, chat_id: int, user_id: int) -> bool:
    """Return True if user is a group admin or creator."""
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status.value in ("administrator", "creator")
    except Exception:
        return False

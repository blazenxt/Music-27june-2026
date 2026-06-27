"""
helpers.py — Audio resolution with Spotify-first approach + YouTube cookies.

Flow for any query:
  Spotify URL  →  spotipy metadata  →  smart YouTube search  →  yt-dlp stream URL
  YouTube URL  →  yt-dlp (with cookies)
  Text query   →  yt-dlp search (with cookies)

Cookies fix:
  - "Sign in to confirm you're not a bot" errors
  - Age-restricted videos
  - Some region-locked content
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional

import yt_dlp

from config import YT_COOKIES_FILE, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

log = logging.getLogger(__name__)

# ── Spotify init ──────────────────────────────────────────────────────────────

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        _sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
            )
        )
        SPOTIFY_ENABLED = True
        log.info("Spotify: enabled")
    else:
        SPOTIFY_ENABLED = False
        _sp = None
        log.info("Spotify: disabled (no credentials)")
except ImportError:
    SPOTIFY_ENABLED = False
    _sp = None
    log.warning("Spotify: spotipy not installed — run: pip install spotipy")

# ── Regex ─────────────────────────────────────────────────────────────────────

SPOTIFY_TRACK_RE    = re.compile(r"spotify\.com/track/([A-Za-z0-9]+)")
SPOTIFY_PLAYLIST_RE = re.compile(r"spotify\.com/playlist/([A-Za-z0-9]+)")
SPOTIFY_ALBUM_RE    = re.compile(r"spotify\.com/album/([A-Za-z0-9]+)")
SPOTIFY_ARTIST_RE   = re.compile(r"spotify\.com/artist/([A-Za-z0-9]+)")


# ── yt-dlp options (with cookies) ────────────────────────────────────────────

def _make_ydl_opts(extra: dict = {}) -> dict:
    """Build yt-dlp options, injecting cookies file if it exists."""
    opts = {
        "format":         "bestaudio/best",
        "quiet":          True,
        "no_warnings":    True,
        "extract_flat":   False,
        "default_search": "ytsearch1",
        "socket_timeout": 20,
        # Spoof a real browser User-Agent
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        **extra,
    }
    # Inject cookies if file exists
    cookie_path = Path(YT_COOKIES_FILE)
    if cookie_path.exists():
        opts["cookiefile"] = str(cookie_path)
        log.debug("Using cookies from %s", cookie_path)
    else:
        log.debug("No cookies file at %s — YouTube may rate-limit", cookie_path)
    return opts


# ── Spotify: metadata extraction ──────────────────────────────────────────────

def _sp_track_meta(track_id: str) -> dict:
    """Return rich metadata dict for a Spotify track ID."""
    t = _sp.track(track_id)
    artists = ", ".join(a["name"] for a in t["artists"])
    return {
        "spotify_id":  track_id,
        "title":       t["name"],
        "artist":      artists,
        "album":       t["album"]["name"],
        "duration_ms": t["duration_ms"],
        "duration":    t["duration_ms"] // 1000,
        "thumbnail":   t["album"]["images"][0]["url"] if t["album"]["images"] else "",
        "spotify_url": t["external_urls"].get("spotify", ""),
        # Search query for YouTube
        "_yt_query":   f"{artists} - {t['name']} official audio",
    }


def get_spotify_track(track_id: str) -> dict:
    return _sp_track_meta(track_id)


def get_spotify_playlist_tracks(playlist_id: str, limit: int = 50) -> list[dict]:
    results = _sp.playlist_items(playlist_id, additional_types=("track",), limit=100)
    tracks  = []
    while results and len(tracks) < limit:
        for item in results["items"]:
            t = item.get("track")
            if not t or not t.get("id"):
                continue
            artists = ", ".join(a["name"] for a in t["artists"])
            tracks.append({
                "spotify_id":  t["id"],
                "title":       t["name"],
                "artist":      artists,
                "album":       t["album"]["name"],
                "duration":    t["duration_ms"] // 1000,
                "duration_ms": t["duration_ms"],
                "thumbnail":   t["album"]["images"][0]["url"] if t["album"]["images"] else "",
                "spotify_url": t["external_urls"].get("spotify", ""),
                "_yt_query":   f"{artists} - {t['name']} official audio",
                "url":         None,   # resolved lazily on play
                "webpage_url": "",
            })
        results = _sp.next(results) if results and results.get("next") else None
    return tracks[:limit]


def get_spotify_album_tracks(album_id: str) -> list[dict]:
    album   = _sp.album(album_id)
    artist  = album["artists"][0]["name"]
    thumb   = album["images"][0]["url"] if album["images"] else ""
    results = _sp.album_tracks(album_id)
    tracks  = []
    for t in results["items"]:
        all_artists = ", ".join(a["name"] for a in t["artists"])
        tracks.append({
            "spotify_id":  t["id"],
            "title":       t["name"],
            "artist":      all_artists,
            "album":       album["name"],
            "duration":    t["duration_ms"] // 1000,
            "duration_ms": t["duration_ms"],
            "thumbnail":   thumb,
            "spotify_url": t["external_urls"].get("spotify", ""),
            "_yt_query":   f"{all_artists} - {t['name']} official audio",
            "url":         None,
            "webpage_url": "",
        })
    return tracks


def get_spotify_artist_top(artist_id: str, country: str = "IN") -> list[dict]:
    data    = _sp.artist_top_tracks(artist_id, country=country)
    artist  = _sp.artist(artist_id)["name"]
    tracks  = []
    for t in data["tracks"]:
        tracks.append({
            "spotify_id":  t["id"],
            "title":       t["name"],
            "artist":      artist,
            "album":       t["album"]["name"],
            "duration":    t["duration_ms"] // 1000,
            "duration_ms": t["duration_ms"],
            "thumbnail":   t["album"]["images"][0]["url"] if t["album"]["images"] else "",
            "spotify_url": t["external_urls"].get("spotify", ""),
            "_yt_query":   f"{artist} - {t['name']} official audio",
            "url":         None,
            "webpage_url": "",
        })
    return tracks


def resolve_spotify(url: str) -> list[dict]:
    """
    Parse any Spotify URL and return a list of track dicts.
    Each dict has: title, artist, duration, thumbnail, spotify_url, _yt_query, url=None
    """
    if not SPOTIFY_ENABLED or not _sp:
        return []
    m = SPOTIFY_TRACK_RE.search(url)
    if m:
        meta = _sp_track_meta(m.group(1))
        return [{**meta, "url": None, "webpage_url": ""}]
    m = SPOTIFY_PLAYLIST_RE.search(url)
    if m:
        return get_spotify_playlist_tracks(m.group(1))
    m = SPOTIFY_ALBUM_RE.search(url)
    if m:
        return get_spotify_album_tracks(m.group(1))
    m = SPOTIFY_ARTIST_RE.search(url)
    if m:
        return get_spotify_artist_top(m.group(1))
    return []


# ── YouTube resolution ────────────────────────────────────────────────────────

def _ydl_extract(query: str) -> dict:
    with yt_dlp.YoutubeDL(_make_ydl_opts()) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info


def _ydl_search_best_match(yt_query: str, duration_ms: int) -> dict:
    """
    Search YouTube for yt_query, then pick the result whose duration is
    closest to the Spotify track's duration (avoids getting a live version
    or a cover by mistake).
    """
    opts = _make_ydl_opts({
        "extract_flat": "in_playlist",
        "default_search": "ytsearch5",  # fetch 5 candidates
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        results = ydl.extract_info(yt_query, download=False)
        entries = results.get("entries", [])

    if not entries:
        # Fallback to first result
        return _ydl_extract(yt_query)

    # Score by duration proximity (within 10 s = perfect)
    target_s = duration_ms / 1000
    best      = None
    best_diff = float("inf")
    for e in entries:
        if not e:
            continue
        diff = abs((e.get("duration") or 0) - target_s)
        if diff < best_diff:
            best_diff = diff
            best      = e

    if best is None:
        return _ydl_extract(yt_query)

    # Now fully extract the winner
    yt_url = best.get("url") or best.get("webpage_url", "")
    return _ydl_extract(yt_url)


async def resolve_yt_for_spotify(track: dict) -> dict:
    """
    Given a Spotify track dict (with _yt_query and duration_ms),
    resolve the actual streamable YouTube URL and merge it in.
    """
    loop     = asyncio.get_event_loop()
    yt_query = track.get("_yt_query") or track.get("title", "")
    dur_ms   = track.get("duration_ms") or (track.get("duration", 0) * 1000)

    info = await loop.run_in_executor(
        None, _ydl_search_best_match, yt_query, dur_ms
    )
    track["url"]         = info["url"]
    track["webpage_url"] = info.get("webpage_url", "")
    # Keep Spotify thumbnail if we have it, else use YouTube's
    if not track.get("thumbnail"):
        track["thumbnail"] = info.get("thumbnail", "")
    return track


async def get_track_info(query: str) -> dict:
    """
    Universal resolver:
      - Spotify URL  → spotipy metadata + smart YT match
      - YouTube URL / text → yt-dlp with cookies
    Returns: { title, artist, url, duration, thumbnail, webpage_url, spotify_url? }
    """
    if "spotify.com" in query and SPOTIFY_ENABLED:
        tracks = resolve_spotify(query)
        if tracks:
            return await resolve_yt_for_spotify(tracks[0])

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _ydl_extract, query)
    return {
        "title":       info.get("title", "Unknown"),
        "artist":      info.get("uploader", ""),
        "url":         info["url"],
        "duration":    info.get("duration", 0),
        "thumbnail":   info.get("thumbnail", ""),
        "webpage_url": info.get("webpage_url", ""),
        "spotify_url": "",
    }


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    h, rem  = divmod(seconds, 3600)
    m, s    = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def progress_bar(elapsed: float, total: float, width: int = 12) -> str:
    if total <= 0:
        return "─" * width
    filled = min(int(width * elapsed / total), width)
    return "▓" * filled + "░" * (width - filled)


# ── Admin check ───────────────────────────────────────────────────────────────

async def is_admin(client, chat_id: int, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status.value in ("administrator", "creator")
    except Exception:
        return False

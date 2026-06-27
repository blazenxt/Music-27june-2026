"""
helpers.py — Audio resolution using spotdl (no Spotify Premium needed).

Flow:
  Spotify URL  →  spotdl fetches metadata  →  smart YouTube duration-match  →  stream
  YouTube URL  →  yt-dlp with cookies
  Text search  →  yt-dlp with cookies

Why spotdl?
  - No API key needed, no Premium account needed
  - Internally uses Spotify's public web scraping + YouTube Music matching
  - Handles: track, playlist, album, artist, liked songs
"""

import asyncio
import logging
import re
import shutil
from pathlib import Path

import yt_dlp

from config import YT_COOKIES_FILE

log = logging.getLogger(__name__)

# ── spotdl init ───────────────────────────────────────────────────────────────

try:
    from spotdl import Spotdl

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg is not installed or not in PATH")

    _spotdl = Spotdl(
        client_id="5f573c9620494bae87890c0f08a60293",   # spotdl public client id
        client_secret="212476d9b0f3472eaa762d90b19b0ba8", # spotdl public secret
        downloader_settings={"ffmpeg": ffmpeg_path},
    )
    SPOTIFY_ENABLED = True
    log.info("spotdl: ready (no Premium needed)")
except ImportError:
    SPOTIFY_ENABLED = False
    _spotdl = None
    log.warning("spotdl not installed — Spotify links disabled. Run: pip install spotdl")
except Exception as e:
    SPOTIFY_ENABLED = False
    _spotdl = None
    log.warning("spotdl disabled: %s", e)

# ── Regex ─────────────────────────────────────────────────────────────────────

SPOTIFY_RE = re.compile(r"https?://open\.spotify\.com/(track|playlist|album|artist)/[A-Za-z0-9]+")


def _normalise_query(query: str) -> str:
    """Clean user input before passing it to yt-dlp.

    Users often type `/play spotify:song name`. That is not a Spotify URL;
    yt-dlp treats it as an unsupported URL scheme. Convert it to plain search.
    Real Spotify URLs are still handled by spotdl.
    """
    query = (query or "").strip()
    if query.lower().startswith("spotify:") and "open.spotify.com" not in query.lower():
        query = query.split(":", 1)[1].strip()
    return query


# ── yt-dlp options ────────────────────────────────────────────────────────────

def _make_ydl_opts(extra: dict = {}) -> dict:
    opts = {
        "format":         "bestaudio/best",
        "quiet":          True,
        "no_warnings":    True,
        "extract_flat":   False,
        "default_search": "ytsearch1",
        "socket_timeout": 20,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                # Helps on many hosts, but cookies may still be required by YouTube.
                "player_client": ["android", "web"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        **extra,
    }
    cookie_path = Path(YT_COOKIES_FILE)
    if cookie_path.exists():
        opts["cookiefile"] = str(cookie_path)
    return opts


# ── spotdl: Spotify → track metadata ─────────────────────────────────────────

def _spotdl_search(url: str) -> list[dict]:
    """
    Use spotdl to fetch Spotify metadata for any URL.
    Returns list of track dicts with: title, artist, album, duration, thumbnail,
    spotify_url, _yt_query, url=None
    """
    songs, _ = _spotdl.search([url])
    result = []
    for s in songs:
        artists = ", ".join(s.artists) if s.artists else s.artist
        result.append({
            "title":       s.name,
            "artist":      artists,
            "album":       s.album_name or "",
            "duration":    s.duration or 0,
            "duration_ms": (s.duration or 0) * 1000,
            "thumbnail":   s.cover_url or "",
            "spotify_url": s.url or url,
            "_yt_query":   f"{artists} - {s.name}",
            "url":         None,
            "webpage_url": "",
        })
    return result


def resolve_spotify(url: str) -> list[dict]:
    """Public API — parse any Spotify URL and return track dicts."""
    if not SPOTIFY_ENABLED or not _spotdl:
        return []
    try:
        return _spotdl_search(url)
    except Exception as e:
        log.error("spotdl failed for %s: %s", url, e)
        return []


# ── YouTube resolution ────────────────────────────────────────────────────────

def _ydl_extract(query: str) -> dict:
    with yt_dlp.YoutubeDL(_make_ydl_opts()) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info


def _ydl_best_match(yt_query: str, duration_s: float) -> dict:
    """
    Search YouTube, pick result closest in duration to target.
    Avoids live versions, covers, remixes.
    """
    opts = _make_ydl_opts({
        "extract_flat":   "in_playlist",
        "default_search": "ytsearch5",
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        results = ydl.extract_info(yt_query, download=False)
        entries = results.get("entries") or []

    if not entries:
        return _ydl_extract(yt_query)

    best, best_diff = None, float("inf")
    for e in entries:
        if not e:
            continue
        diff = abs((e.get("duration") or 0) - duration_s)
        if diff < best_diff:
            best_diff = diff
            best = e

    yt_url = (best or {}).get("url") or (best or {}).get("webpage_url") or yt_query
    return _ydl_extract(yt_url)


async def resolve_yt_for_spotify(track: dict) -> dict:
    """Resolve streamable YouTube URL for a Spotify track dict."""
    loop      = asyncio.get_event_loop()
    yt_query  = track.get("_yt_query") or track.get("title", "")
    duration_s = track.get("duration") or track.get("duration_ms", 0) / 1000

    info = await loop.run_in_executor(None, _ydl_best_match, yt_query, duration_s)
    track["url"]         = info["url"]
    track["webpage_url"] = info.get("webpage_url", "")
    if not track.get("thumbnail"):
        track["thumbnail"] = info.get("thumbnail", "")
    return track


async def get_track_info(query: str) -> dict:
    """
    Universal resolver:
      Spotify URL → spotdl metadata → best YouTube match
      YouTube URL / text → yt-dlp with cookies
    """
    query = _normalise_query(query)
    if not query:
        raise ValueError("Empty query. Send a song name, YouTube URL, or full Spotify URL.")

    if "spotify.com" in query and SPOTIFY_ENABLED:
        loop   = asyncio.get_event_loop()
        tracks = await loop.run_in_executor(None, resolve_spotify, query)
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

"""
radio.py — Spotify-first radio.

Priority:
  1. If Spotify credentials set  → use curated Spotify playlist for genre
  2. Fallback                    → YouTube playlist search (yt-dlp)

Spotify radio is much better quality: real editorial playlists, accurate
metadata, correct durations for smart YT matching.
"""

import asyncio
import logging
import random
from pathlib import Path

import yt_dlp

from config import (
    RADIO_PREFER_SPOTIFY,
    SPOTIFY_GENRE_PLAYLISTS,
    YT_COOKIES_FILE,
)

log = logging.getLogger(__name__)

RADIO_BATCH = 20

# YouTube fallback seeds (when Spotify not available)
YT_GENRE_SEEDS: dict[str, list[str]] = {
    "lofi":       ["lofi hip hop radio beats to study", "lofi chill beats playlist"],
    "hiphop":     ["hip hop playlist 2024", "rap classics mix"],
    "pop":        ["pop hits 2024 playlist", "top pop songs mix"],
    "rock":       ["rock classics playlist", "alternative rock mix"],
    "electronic": ["electronic music mix 2024", "EDM playlist"],
    "jazz":       ["jazz playlist relaxing", "smooth jazz mix"],
    "classical":  ["classical music playlist", "piano classics mix"],
    "rnb":        ["R&B hits playlist", "soul R&B mix"],
    "metal":      ["metal playlist 2024", "heavy metal mix"],
    "country":    ["country hits playlist", "country music mix"],
    "kpop":       ["kpop playlist 2024", "kpop hits mix"],
    "anime":      ["anime ost playlist", "anime music mix"],
    "gaming":     ["gaming music playlist", "video game ost mix"],
    "sleep":      ["sleep music playlist", "relaxing music for sleep"],
    "workout":    ["workout motivation music", "gym playlist 2024"],
    "reggae":     ["reggae playlist", "reggae classics mix"],
}

AVAILABLE_GENRES = sorted(set(list(SPOTIFY_GENRE_PLAYLISTS.keys()) + list(YT_GENRE_SEEDS.keys())))


# ── Spotify radio ─────────────────────────────────────────────────────────────

def _spotify_radio(genre: str, limit: int = RADIO_BATCH) -> list[dict]:
    """Fetch tracks from a curated Spotify genre playlist."""
    from helpers import get_spotify_playlist_tracks, SPOTIFY_ENABLED
    if not SPOTIFY_ENABLED:
        return []
    playlist_id = SPOTIFY_GENRE_PLAYLISTS.get(genre.lower())
    if not playlist_id:
        return []
    tracks = get_spotify_playlist_tracks(playlist_id, limit=limit)
    random.shuffle(tracks)
    log.info("Spotify radio: loaded %d tracks for genre '%s'", len(tracks), genre)
    return tracks


# ── YouTube fallback radio ────────────────────────────────────────────────────

def _make_ydl_opts() -> dict:
    opts = {
        "quiet":          True,
        "no_warnings":    True,
        "extract_flat":   "in_playlist",
        "playlistend":    RADIO_BATCH,
        "default_search": "ytsearch1",
        "socket_timeout": 15,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    }
    cookie_path = Path(YT_COOKIES_FILE)
    if cookie_path.exists():
        opts["cookiefile"] = str(cookie_path)
    return opts


def _yt_radio(seed: str) -> list[dict]:
    tracks = []
    with yt_dlp.YoutubeDL(_make_ydl_opts()) as ydl:
        info    = ydl.extract_info(seed, download=False)
        entries = info.get("entries") or [info]
        for e in entries:
            if not e:
                continue
            tracks.append({
                "title":       e.get("title", "Unknown"),
                "artist":      e.get("uploader", ""),
                "url":         None,
                "duration":    e.get("duration", 0),
                "thumbnail":   e.get("thumbnail", ""),
                "webpage_url": e.get("url") or e.get("webpage_url", ""),
                "_yt_query":   e.get("url") or e.get("webpage_url", ""),
            })
    log.info("YT radio: loaded %d tracks for seed '%s'", len(tracks), seed)
    return tracks[:RADIO_BATCH]


# ── Public API ────────────────────────────────────────────────────────────────

async def get_radio_tracks(genre: str) -> tuple[str, list[dict], str]:
    """
    Returns (label, tracks, source) where source is 'spotify' or 'youtube'.
    Tracks are ready to enqueue (url=None, resolved lazily on play).
    """
    genre = genre.lower().strip()
    loop  = asyncio.get_event_loop()

    # Try Spotify first
    if RADIO_PREFER_SPOTIFY and SPOTIFY_GENRE_PLAYLISTS.get(genre):
        try:
            from helpers import SPOTIFY_ENABLED
            if SPOTIFY_ENABLED:
                tracks = await loop.run_in_executor(None, _spotify_radio, genre)
                if tracks:
                    return genre, tracks, "spotify"
        except Exception as e:
            log.warning("Spotify radio failed, falling back to YT: %s", e)

    # YouTube fallback
    seeds = YT_GENRE_SEEDS.get(genre)
    seed  = random.choice(seeds) if seeds else f"{genre} music playlist"
    tracks = await loop.run_in_executor(None, _yt_radio, seed)
    return genre, tracks, "youtube"

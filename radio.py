"""
radio.py — Genre/mood radio: seeds the queue with related tracks.

Strategy: search YouTube for '<genre> mix playlist', grab the first
playlist's entries (up to RADIO_BATCH), and enqueue them.
Falls back to individual track searches if no playlist found.
"""

import asyncio
import logging
import random
from typing import Optional
import yt_dlp

log = logging.getLogger(__name__)

RADIO_BATCH = 15   # tracks to enqueue per radio seed

# Curated seeds so "lo-fi" doesn't always return the same mix
GENRE_SEEDS: dict[str, list[str]] = {
    "lofi":       ["lofi hip hop radio beats to study", "lofi chill beats playlist", "lofi jazz playlist"],
    "hiphop":     ["hip hop playlist 2024", "rap classics mix", "underground hip hop mix"],
    "pop":        ["pop hits 2024 playlist", "top pop songs mix", "pop music playlist"],
    "rock":       ["rock classics playlist", "alternative rock mix", "indie rock playlist"],
    "electronic": ["electronic music mix 2024", "EDM playlist", "techno mix playlist"],
    "jazz":       ["jazz playlist relaxing", "smooth jazz mix", "jazz classics"],
    "classical":  ["classical music playlist", "piano classics mix", "orchestral music"],
    "rnb":        ["R&B hits playlist", "soul R&B mix", "neo soul playlist"],
    "metal":      ["metal playlist 2024", "heavy metal mix", "classic metal songs"],
    "country":    ["country hits playlist", "country music mix", "classic country songs"],
    "reggae":     ["reggae playlist", "reggae classics mix", "roots reggae"],
    "kpop":       ["kpop playlist 2024", "kpop hits mix", "kpop songs"],
    "anime":      ["anime ost playlist", "anime music mix", "best anime openings"],
    "gaming":     ["gaming music playlist", "video game ost mix", "game soundtrack mix"],
    "sleep":      ["sleep music playlist", "relaxing music for sleep", "ambient sleep sounds"],
    "workout":    ["workout motivation music", "gym playlist 2024", "workout hits mix"],
}

AVAILABLE_GENRES = sorted(GENRE_SEEDS.keys())


def _pick_seed(genre: str) -> str:
    genre = genre.lower().strip()
    seeds = GENRE_SEEDS.get(genre)
    if seeds:
        return random.choice(seeds)
    # Free-form: just use what the user typed
    return f"{genre} music playlist"


def _ydl_fetch_radio(search: str) -> list[dict]:
    """Synchronous yt-dlp call — run in executor."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": RADIO_BATCH,
        "default_search": "ytsearch1",
        "socket_timeout": 15,
    }
    tracks = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search, download=False)
        entries = info.get("entries") or [info]
        for e in entries:
            if not e:
                continue
            tracks.append({
                "title":       e.get("title", "Unknown"),
                "url":         None,           # lazy — resolved on play
                "duration":    e.get("duration", 0),
                "thumbnail":   e.get("thumbnail", ""),
                "webpage_url": e.get("url") or e.get("webpage_url", ""),
                "_query":      e.get("url") or e.get("webpage_url", ""),
            })
    return tracks[:RADIO_BATCH]


async def get_radio_tracks(genre: str) -> tuple[str, list[dict]]:
    """
    Return (resolved_genre_label, list_of_track_stubs).
    Tracks have url=None and _query=youtube_url; player resolves on demand.
    """
    seed = _pick_seed(genre)
    log.info("Radio seed: %r", seed)
    loop   = asyncio.get_event_loop()
    tracks = await loop.run_in_executor(None, _ydl_fetch_radio, seed)
    return seed, tracks

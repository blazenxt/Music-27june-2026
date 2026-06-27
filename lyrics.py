"""
lyrics.py — Fetch song lyrics.

Uses lyrics.ovh (free, no API key) with a lrclib.net fallback.
Returns plain text or a friendly error string.
"""

import asyncio
import logging
import re
import aiohttp

log = logging.getLogger(__name__)

_SESSION: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        _SESSION = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
    return _SESSION


def _parse_title(title: str) -> tuple[str, str]:
    """
    Try to split 'Artist - Title' or 'Title (Official Video)' into (artist, song).
    Returns ('', title) if we can't figure it out.
    """
    title = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
    if " - " in title:
        parts = title.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return "", title.strip()


async def _lyrics_ovh(artist: str, song: str) -> str | None:
    url = f"https://api.lyrics.ovh/v1/{artist}/{song}"
    try:
        async with _get_session().get(url) as r:
            if r.status == 200:
                data = await r.json()
                return data.get("lyrics")
    except Exception as e:
        log.debug("lyrics.ovh failed: %s", e)
    return None


async def _lrclib(artist: str, song: str) -> str | None:
    url = "https://lrclib.net/api/search"
    try:
        async with _get_session().get(url, params={"q": f"{artist} {song}"}) as r:
            if r.status == 200:
                results = await r.json()
                if results:
                    return results[0].get("plainLyrics") or results[0].get("syncedLyrics")
    except Exception as e:
        log.debug("lrclib failed: %s", e)
    return None


async def get_lyrics(track_title: str, query_override: str = "") -> str:
    """
    Fetch lyrics for a track title.
    Returns a string — either the lyrics or an error message.
    """
    search = query_override or track_title
    artist, song = _parse_title(search)

    # Try lyrics.ovh first (needs artist + song)
    if artist and song:
        text = await _lyrics_ovh(artist, song)
        if text:
            return text.strip()

    # Fallback: lrclib full-text search
    text = await _lrclib(artist or "", song or search)
    if text:
        return text.strip()

    return f"❌ Lyrics not found for **{track_title}**."


async def close():
    global _SESSION
    if _SESSION and not _SESSION.closed:
        await _SESSION.close()

"""
player.py — Core playback engine (v3).
Adds: DB persistence, history logging, retry on stale URL,
radio auto-refill, vote-skip reset on track change.
"""

import asyncio
import logging

from pytgcalls import PyTgCalls, idle
from pytgcalls.types import AudioPiped
from pytgcalls.exceptions import NoActiveGroupCall, AlreadyJoinedError

import state
import database as db
import voteskip
from keyboards import player_keyboard
from helpers import fmt_duration, progress_bar, get_track_info
from config import RADIO_AUTO_REFILL, RADIO_REFILL_AT

log = logging.getLogger(__name__)

call_py: PyTgCalls = None
_app = None


def init(pyrogram_client, pytgcalls_client: PyTgCalls):
    global _app, call_py
    _app    = pyrogram_client
    call_py = pytgcalls_client


# ── URL freshness ─────────────────────────────────────────────────────────────

async def _ensure_fresh_url(track: dict) -> dict:
    """
    Re-fetch the direct audio URL if missing or stale.
    For Spotify tracks: uses smart YT duration-matching via resolve_yt_for_spotify.
    For YouTube stubs: re-extracts via yt-dlp with cookies.
    yt-dlp stream URLs expire after ~6h; permanent keys are _yt_query / webpage_url.
    """
    if track.get("url"):
        return track   # still fresh

    # Spotify track — use smart matching
    if track.get("spotify_id") or track.get("spotify_url") or track.get("_yt_query"):
        from helpers import resolve_yt_for_spotify
        log.info("Resolving Spotify→YT for: %s", track.get("title"))
        return await resolve_yt_for_spotify(track)

    # Plain YouTube stub
    query = track.get("webpage_url") or track.get("title")
    if not query:
        raise ValueError(f"No resolvable query for track: {track.get('title')}")
    log.info("Re-fetching YT URL for: %s", track.get("title"))
    fresh = await get_track_info(query)
    track.update(fresh)
    return track


# ── Now-playing message ───────────────────────────────────────────────────────

def _np_text(st: state.ChatState) -> str:
    track = st.current
    if not track:
        return "Nothing playing."
    dur     = track.get("duration", 0)
    elapsed = st.elapsed
    bar     = progress_bar(elapsed, dur)
    radio   = " 📻" if st.radio_mode else ""
    loop    = " 🔁" if st.loop else ""
    lines   = [
        f"🎵 **{track['title']}**{radio}{loop}",
        f"`{bar}` {fmt_duration(elapsed)} / {fmt_duration(dur)}",
        f"Vol: {st.volume}",
    ]
    if track.get("webpage_url"):
        lines.append(f"[Open on YouTube]({track['webpage_url']})")
    return "\n".join(lines)


async def send_np_message(chat_id: int):
    st   = state.get(chat_id)
    text = _np_text(st)
    kb   = player_keyboard(paused=st.paused, loop=st.loop)
    try:
        if st.np_message_id:
            await _app.edit_message_text(
                chat_id, st.np_message_id, text,
                reply_markup=kb, disable_web_page_preview=True,
            )
        else:
            msg = await _app.send_message(
                chat_id, text,
                reply_markup=kb, disable_web_page_preview=True,
            )
            st.np_message_id = msg.id
    except Exception as e:
        log.warning("NP message update failed: %s", e)


async def refresh_np(chat_id: int):
    await send_np_message(chat_id)


# ── Radio refill ──────────────────────────────────────────────────────────────

async def _maybe_refill_radio(chat_id: int):
    if not RADIO_AUTO_REFILL:
        return
    st = state.get(chat_id)
    if not st.radio_mode or len(st.queue) > RADIO_REFILL_AT:
        return
    from radio import get_radio_tracks
    log.info("Radio refill for chat %d (genre: %s)", chat_id, st.radio_genre)
    try:
        _, new_tracks = await get_radio_tracks(st.radio_genre)
        # Don't re-add tracks already in queue
        existing = {t.get("webpage_url") for t in st.queue if t.get("webpage_url")}
        for t in new_tracks:
            if t.get("webpage_url") not in existing:
                st.queue.append(t)
        await db.save_queue(chat_id, st.queue)
    except Exception as e:
        log.warning("Radio refill failed: %s", e)


# ── Core playback ─────────────────────────────────────────────────────────────

async def play_current(chat_id: int, first: bool = False):
    st = state.get(chat_id)
    if not st.current:
        return

    # Ensure we have a streamable URL
    try:
        st.queue[0] = await _ensure_fresh_url(st.queue[0])
    except Exception as e:
        log.error("URL resolution failed: %s", e)
        await _app.send_message(chat_id, f"⚠️ Skipping **{st.current.get('title')}** — could not load audio.")
        await skip(chat_id)
        return

    url = st.current["url"]
    try:
        if first:
            await call_py.join_group_call(chat_id, AudioPiped(url))
        else:
            await call_py.change_stream(chat_id, AudioPiped(url))
        await call_py.change_volume_call(chat_id, st.volume)
        st.mark_started()
        # Log to history
        asyncio.ensure_future(db.push_history(chat_id, st.current))
        # Reset vote-skip for this new track
        voteskip.reset(chat_id)
        # Persist queue
        asyncio.ensure_future(db.save_queue(chat_id, st.queue))
        # Delete old NP message, send fresh one
        if st.np_message_id:
            try:
                await _app.delete_messages(chat_id, st.np_message_id)
            except Exception:
                pass
            st.np_message_id = None
        await send_np_message(chat_id)
        # Maybe refill radio queue
        asyncio.ensure_future(_maybe_refill_radio(chat_id))

    except AlreadyJoinedError:
        await call_py.change_stream(chat_id, AudioPiped(url))
        st.mark_started()
        await send_np_message(chat_id)
    except NoActiveGroupCall:
        raise
    except Exception as e:
        log.error("play_current error: %s", e)
        raise


async def skip(chat_id: int):
    st = state.get(chat_id)
    if not st.queue:
        return False
    if st.loop:
        st.queue.append(st.queue.pop(0))
    else:
        st.queue.pop(0)
    voteskip.reset(chat_id)
    if st.queue:
        await play_current(chat_id)
    else:
        await stop(chat_id)
    return True


async def stop(chat_id: int):
    st = state.get(chat_id)
    st.queue.clear()
    try:
        await call_py.leave_group_call(chat_id)
    except Exception:
        pass
    if st.np_message_id:
        try:
            await _app.edit_message_text(chat_id, st.np_message_id, "⏹ Playback stopped.")
        except Exception:
            pass
        st.np_message_id = None
    await db.clear_queue(chat_id)
    state.clear(chat_id)


async def pause(chat_id: int):
    st = state.get(chat_id)
    if st.paused:
        return
    await call_py.pause_stream(chat_id)
    st.mark_paused()
    await refresh_np(chat_id)


async def resume(chat_id: int):
    st = state.get(chat_id)
    if not st.paused:
        return
    await call_py.resume_stream(chat_id)
    st.mark_resumed()
    await refresh_np(chat_id)


async def set_volume(chat_id: int, vol: int):
    vol = max(0, min(200, vol))
    st  = state.get(chat_id)
    st.volume = vol
    await call_py.change_volume_call(chat_id, vol)
    await db.set_setting(chat_id, "volume", vol)
    await refresh_np(chat_id)


async def toggle_loop(chat_id: int):
    st      = state.get(chat_id)
    st.loop = not st.loop
    await db.set_setting(chat_id, "loop", int(st.loop))
    await refresh_np(chat_id)
    return st.loop


# ── Stream-end handler ────────────────────────────────────────────────────────

async def on_stream_end(_, update):
    chat_id = update.chat_id
    st      = state.get(chat_id)
    if not st.queue:
        state.clear(chat_id)
        await db.clear_queue(chat_id)
        return
    st.advance()
    if st.queue:
        try:
            await play_current(chat_id)
        except Exception as e:
            log.error("Auto-advance failed: %s — trying skip", e)
            await skip(chat_id)
    else:
        try:
            await call_py.leave_group_call(chat_id)
        except Exception:
            pass
        await db.clear_queue(chat_id)
        state.clear(chat_id)

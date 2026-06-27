"""
player.py — Core playback engine.

Compatible with py-tgcalls 2.x. Handles playback, queue advancement,
now-playing messages, history persistence, radio refill and vote-skip reset.
"""

import asyncio
import logging

from pytgcalls import PyTgCalls
from pytgcalls.types import GroupCallConfig, MediaStream
from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError

import state
import database as db
import voteskip
from keyboards import player_keyboard
from helpers import fmt_duration, progress_bar, get_track_info
from config import RADIO_AUTO_REFILL, RADIO_REFILL_AT

log = logging.getLogger(__name__)

call_py: PyTgCalls | None = None
_app = None


def init(pyrogram_client, pytgcalls_client: PyTgCalls):
    global _app, call_py
    _app = pyrogram_client
    call_py = pytgcalls_client


# ── URL freshness ─────────────────────────────────────────────────────────────

async def _ensure_fresh_url(track: dict) -> dict:
    """
    Make sure a track has a streamable URL.

    yt-dlp stream URLs can expire. Saved queues keep stable identifiers like
    _yt_query/webpage_url so tracks can be resolved again after restart.
    """
    if track.get("url"):
        return track

    if track.get("spotify_id") or track.get("spotify_url") or track.get("_yt_query"):
        from helpers import resolve_yt_for_spotify
        log.info("Resolving track to YouTube: %s", track.get("title"))
        return await resolve_yt_for_spotify(track)

    query = track.get("webpage_url") or track.get("title")
    if not query:
        raise ValueError(f"No resolvable query for track: {track.get('title')}")

    log.info("Re-fetching YouTube URL for: %s", track.get("title"))
    fresh = await get_track_info(query)
    track.update(fresh)
    return track


# ── Now-playing message ───────────────────────────────────────────────────────

def _np_text(st: state.ChatState) -> str:
    track = st.current
    if not track:
        return "Nothing playing."

    dur = track.get("duration", 0)
    elapsed = st.elapsed
    bar = progress_bar(elapsed, dur)
    radio = " 📻" if st.radio_mode else ""
    loop = " 🔁" if st.loop else ""

    lines = [
        f"🎵 **{track.get('title', 'Unknown')}**{radio}{loop}",
        f"`{bar}` {fmt_duration(elapsed)} / {fmt_duration(dur)}",
        f"Vol: {st.volume}",
    ]
    if track.get("webpage_url"):
        lines.append(f"[Open on YouTube]({track['webpage_url']})")
    return "\n".join(lines)


async def send_np_message(chat_id: int):
    st = state.get(chat_id)
    text = _np_text(st)
    kb = player_keyboard(paused=st.paused, loop=st.loop)
    try:
        if st.np_message_id:
            await _app.edit_message_text(
                chat_id,
                st.np_message_id,
                text,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        else:
            msg = await _app.send_message(
                chat_id,
                text,
                reply_markup=kb,
                disable_web_page_preview=True,
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
        _, new_tracks, _ = await get_radio_tracks(st.radio_genre)
        existing = {
            t.get("webpage_url") or t.get("_yt_query") or t.get("title")
            for t in st.queue
        }
        for t in new_tracks:
            key = t.get("webpage_url") or t.get("_yt_query") or t.get("title")
            if key not in existing:
                st.queue.append(t)
                existing.add(key)
        await db.save_queue(chat_id, st.queue)
    except Exception as e:
        log.warning("Radio refill failed: %s", e)


# ── Core playback ─────────────────────────────────────────────────────────────

async def play_current(chat_id: int, first: bool = False):
    st = state.get(chat_id)
    if not st.current:
        return
    if call_py is None:
        await _app.send_message(
            chat_id,
            "❌ Voice userbot is not configured. Owner must generate/set SESSION_STRING and restart."
        )
        return

    try:
        st.queue[0] = await _ensure_fresh_url(st.queue[0])
    except Exception as e:
        log.error("URL resolution failed: %s", e)
        await _app.send_message(
            chat_id,
            f"⚠️ Skipping **{st.current.get('title', 'Unknown')}** — could not load audio.",
        )
        await skip(chat_id)
        return

    url = st.current["url"]
    try:
        # In py-tgcalls 2.x, play() both joins and changes an existing stream.
        # auto_start=False keeps the old behaviour: user must start VC first.
        await call_py.play(
            chat_id,
            MediaStream(url),
            GroupCallConfig(auto_start=False),
        )
        await call_py.change_volume_call(chat_id, st.volume)
        st.mark_started()

        asyncio.create_task(db.push_history(chat_id, st.current))
        voteskip.reset(chat_id)
        asyncio.create_task(db.save_queue(chat_id, st.queue))

        if st.np_message_id:
            try:
                await _app.delete_messages(chat_id, st.np_message_id)
            except Exception:
                pass
            st.np_message_id = None

        await send_np_message(chat_id)
        asyncio.create_task(_maybe_refill_radio(chat_id))

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
        await call_py.leave_call(chat_id)
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
    await call_py.pause(chat_id)
    st.mark_paused()
    await refresh_np(chat_id)


async def resume(chat_id: int):
    st = state.get(chat_id)
    if not st.paused:
        return
    await call_py.resume(chat_id)
    st.mark_resumed()
    await refresh_np(chat_id)


async def set_volume(chat_id: int, vol: int):
    vol = max(0, min(200, vol))
    st = state.get(chat_id)
    st.volume = vol
    await call_py.change_volume_call(chat_id, vol)
    await db.set_setting(chat_id, "volume", vol)
    await refresh_np(chat_id)


async def toggle_loop(chat_id: int):
    st = state.get(chat_id)
    st.loop = not st.loop
    await db.set_setting(chat_id, "loop", int(st.loop))
    await refresh_np(chat_id)
    return st.loop


# ── Stream-end handler ────────────────────────────────────────────────────────

async def on_stream_end(_, update):
    chat_id = update.chat_id
    st = state.get(chat_id)
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
            await call_py.leave_call(chat_id)
        except Exception:
            pass
        await db.clear_queue(chat_id)
        state.clear(chat_id)

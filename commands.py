"""
commands.py — All /command handlers (v3).
New: /lyrics, /radio, /voteskip, /history
"""

import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls.exceptions import NoActiveGroupCall

import state
import player as pl
import database as db
import voteskip as vs
import lyrics as lyr
from radio import get_radio_tracks, AVAILABLE_GENRES
from config import ADMIN_ONLY_CMDS, MAX_QUEUE_SIZE, HISTORY_LIMIT, VOTESKIP_THRESHOLD
from helpers import (
    get_track_info, resolve_spotify, is_admin,
    fmt_duration, SPOTIFY_ENABLED,
)

log = logging.getLogger(__name__)


# ── Guard helpers ─────────────────────────────────────────────────────────────

async def _check_admin(client, msg: Message) -> bool:
    if not ADMIN_ONLY_CMDS:
        return True
    if await is_admin(client, msg.chat.id, msg.from_user.id):
        return True
    await msg.reply("⛔ Only admins can use this command.", quote=True)
    return False


# ── Register all handlers ─────────────────────────────────────────────────────

def register(app: Client):

    # ── /play ─────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("play") & filters.group)
    async def cmd_play(_, msg: Message):
        query = " ".join(msg.command[1:]).strip()
        if not query:
            await msg.reply("Usage: `/play <song, YouTube URL, or Spotify URL>`", quote=True)
            return

        chat_id = msg.chat.id
        st      = state.get(chat_id)

        # Disable radio mode when explicitly playing something
        st.radio_mode = False

        # Spotify playlist / album
        if "spotify.com" in query and SPOTIFY_ENABLED:
            if "playlist" in query or "album" in query:
                status = await msg.reply("🎧 Loading Spotify playlist…", quote=True)
                queries = await asyncio.get_event_loop().run_in_executor(
                    None, resolve_spotify, query
                )
                if not queries:
                    await status.edit("❌ Could not load Spotify playlist.")
                    return
                try:
                    first = await get_track_info(queries[0])
                except Exception as e:
                    await status.edit(f"❌ {e}")
                    return
                st.queue.append(first)
                for q in queries[1 : MAX_QUEUE_SIZE - len(st.queue)]:
                    st.queue.append({"title": q, "url": None, "duration": 0,
                                     "thumbnail": "", "webpage_url": "", "_query": q})
                asyncio.ensure_future(db.save_queue(chat_id, st.queue))
                if len(st.queue) == 1:
                    try:
                        await pl.play_current(chat_id, first=True)
                        await status.edit(f"▶️ Now playing: **{first['title']}**\n"
                                          f"📋 Queued {len(queries)} Spotify tracks.")
                    except NoActiveGroupCall:
                        st.queue.clear()
                        await status.edit("❌ No active voice chat. Start one first.")
                else:
                    await status.edit(f"📋 Queued **{len(queries)} tracks** from Spotify.")
                return

        # Single track
        if len(st.queue) >= MAX_QUEUE_SIZE:
            await msg.reply(f"❌ Queue is full ({MAX_QUEUE_SIZE} tracks).", quote=True)
            return

        status = await msg.reply("🔍 Searching…", quote=True)
        try:
            track = await get_track_info(query)
        except Exception as e:
            await status.edit(f"❌ Could not find track: {e}")
            return

        st.queue.append(track)
        asyncio.ensure_future(db.save_queue(chat_id, st.queue))

        if len(st.queue) == 1:
            try:
                await pl.play_current(chat_id, first=True)
                await status.delete()
            except NoActiveGroupCall:
                st.queue.pop()
                await status.edit("❌ No active voice chat in this group.")
        else:
            await status.edit(
                f"📋 **#{len(st.queue)} in queue:** {track['title']} "
                f"({fmt_duration(track['duration'])})"
            )

    # ── /radio ────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("radio") & filters.group)
    async def cmd_radio(_, msg: Message):
        args = " ".join(msg.command[1:]).strip().lower()
        if not args:
            genres = ", ".join(f"`{g}`" for g in AVAILABLE_GENRES)
            await msg.reply(
                f"📻 **Radio mode** — pick a genre:\n{genres}\n\n"
                "Usage: `/radio lofi`", quote=True
            )
            return

        chat_id = msg.chat.id
        st      = state.get(chat_id)
        status  = await msg.reply(f"📻 Tuning into **{args}** radio…", quote=True)

        try:
            seed, tracks = await get_radio_tracks(args)
        except Exception as e:
            await status.edit(f"❌ Radio failed: {e}")
            return

        if not tracks:
            await status.edit("❌ Couldn't find any tracks for that genre.")
            return

        # Clear current queue, replace with radio tracks
        was_playing = bool(st.queue)
        st.queue.clear()
        st.queue.extend(tracks)
        st.radio_mode  = True
        st.radio_genre = args
        asyncio.ensure_future(db.save_queue(chat_id, st.queue))

        if was_playing:
            # Change stream immediately
            await pl.play_current(chat_id)
            await status.edit(f"📻 Switched to **{args}** radio ({len(tracks)} tracks queued).")
        else:
            try:
                await pl.play_current(chat_id, first=True)
                await status.edit(f"📻 **{args.title()} Radio** started — {len(tracks)} tracks queued.")
            except NoActiveGroupCall:
                st.queue.clear()
                st.radio_mode = False
                await status.edit("❌ No active voice chat. Start one first.")

    # ── /voteskip ─────────────────────────────────────────────────────────────

    @app.on_message(filters.command("voteskip") & filters.group)
    async def cmd_voteskip(client, msg: Message):
        chat_id = msg.chat.id
        st      = state.get(chat_id)
        if not st.current:
            await msg.reply("Nothing is playing.", quote=True)
            return

        user_id = msg.from_user.id

        # Admins can always skip instantly
        if await is_admin(client, chat_id, user_id):
            await pl.skip(chat_id)
            await msg.reply("⏭ Admin skipped.", quote=True)
            return

        is_new = vs.add_vote(chat_id, user_id)
        if not is_new:
            await msg.reply("You already voted to skip.", quote=True)
            return

        member_count = await vs.get_member_count(client, chat_id)
        needed       = vs.needed(member_count)
        current      = vs.vote_count(chat_id)

        if current >= needed:
            vs.reset(chat_id)
            title = st.current["title"]
            await pl.skip(chat_id)
            await msg.reply(f"🗳️ Vote passed ({current}/{needed}) — skipped **{title}**.",
                            quote=True)
        else:
            pct = int(VOTESKIP_THRESHOLD * 100)
            await msg.reply(
                f"🗳️ Skip vote: **{current}/{needed}** "
                f"({pct}% of {member_count} members needed).\n"
                "Use `/voteskip` to add your vote.",
                quote=True,
            )

    # ── /lyrics ───────────────────────────────────────────────────────────────

    @app.on_message(filters.command("lyrics") & filters.group)
    async def cmd_lyrics(_, msg: Message):
        chat_id = msg.chat.id
        st      = state.get(chat_id)

        # Allow /lyrics <song> as override
        override = " ".join(msg.command[1:]).strip()
        if not override and not st.current:
            await msg.reply("Nothing is playing. Use `/lyrics <song name>`.", quote=True)
            return

        title   = override or st.current["title"]
        status  = await msg.reply(f"🔍 Fetching lyrics for **{title}**…", quote=True)
        text    = await lyr.get_lyrics(title)

        # Telegram messages cap at 4096 chars
        if len(text) > 4000:
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            await status.edit(f"📝 **{title}**\n\n{chunks[0]}")
            for chunk in chunks[1:]:
                await msg.reply(chunk, quote=True)
        else:
            await status.edit(f"📝 **{title}**\n\n{text}")

    # ── /history ──────────────────────────────────────────────────────────────

    @app.on_message(filters.command("history") & filters.group)
    async def cmd_history(_, msg: Message):
        rows = await db.get_history(msg.chat.id, limit=HISTORY_LIMIT)
        if not rows:
            await msg.reply("No play history yet.", quote=True)
            return
        import datetime
        lines = []
        for i, r in enumerate(rows, 1):
            ts  = datetime.datetime.fromtimestamp(r["played_at"]).strftime("%m/%d %H:%M")
            dur = fmt_duration(r["duration"])
            url = r.get("webpage_url", "")
            title_text = f"[{r['title']}]({url})" if url else r["title"]
            lines.append(f"`{i}.` {title_text} `{dur}` · {ts}")
        await msg.reply(
            f"📜 **Last {len(rows)} played:**\n" + "\n".join(lines),
            quote=True, disable_web_page_preview=True,
        )

    # ── /skip ─────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("skip") & filters.group)
    async def cmd_skip(client, msg: Message):
        if not await _check_admin(client, msg):
            return
        chat_id = msg.chat.id
        st      = state.get(chat_id)
        if not st.current:
            await msg.reply("Nothing is playing.", quote=True)
            return
        skipped = st.current["title"]
        await pl.skip(chat_id)
        nxt = state.get(chat_id).current
        reply = f"⏭ Skipped **{skipped}**."
        if nxt:
            reply += f"\n▶️ Now: **{nxt['title']}**"
        await msg.reply(reply, quote=True)

    # ── /stop ─────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("stop") & filters.group)
    async def cmd_stop(client, msg: Message):
        if not await _check_admin(client, msg):
            return
        await pl.stop(msg.chat.id)
        await msg.reply("⏹ Stopped and cleared queue.", quote=True)

    # ── /pause & /resume ──────────────────────────────────────────────────────

    @app.on_message(filters.command("pause") & filters.group)
    async def cmd_pause(_, msg: Message):
        st = state.get(msg.chat.id)
        if not st.current:
            await msg.reply("Nothing is playing.", quote=True)
            return
        await pl.pause(msg.chat.id)
        await msg.reply("⏸ Paused.", quote=True)

    @app.on_message(filters.command("resume") & filters.group)
    async def cmd_resume(_, msg: Message):
        st = state.get(msg.chat.id)
        if not st.current:
            await msg.reply("Nothing is playing.", quote=True)
            return
        await pl.resume(msg.chat.id)
        await msg.reply("▶️ Resumed.", quote=True)

    # ── /vol ──────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("vol") & filters.group)
    async def cmd_vol(_, msg: Message):
        args = msg.command[1:]
        if not args or not args[0].isdigit():
            st = state.get(msg.chat.id)
            await msg.reply(f"Current volume: **{st.volume}**. Usage: `/vol 0–200`", quote=True)
            return
        await pl.set_volume(msg.chat.id, int(args[0]))
        await msg.reply(f"🔊 Volume set to **{min(200, max(0, int(args[0])))}**.", quote=True)

    # ── /loop ─────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("loop") & filters.group)
    async def cmd_loop(_, msg: Message):
        on = await pl.toggle_loop(msg.chat.id)
        await msg.reply(f"🔁 Loop mode: **{'ON' if on else 'OFF'}**.", quote=True)

    # ── /queue ────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("queue") & filters.group)
    async def cmd_queue(_, msg: Message):
        q = state.get(msg.chat.id).queue
        if not q:
            await msg.reply("Queue is empty.", quote=True)
            return
        lines = []
        for i, t in enumerate(q[:20]):
            dur  = fmt_duration(t.get("duration", 0))
            icon = "▶️" if i == 0 else f"{i}."
            lines.append(f"{icon} **{t['title']}** `{dur}`")
        if len(q) > 20:
            lines.append(f"…and {len(q) - 20} more")
        await msg.reply("\n".join(lines), quote=True)

    # ── /np ───────────────────────────────────────────────────────────────────

    @app.on_message(filters.command(["np", "nowplaying"]) & filters.group)
    async def cmd_np(_, msg: Message):
        st = state.get(msg.chat.id)
        if not st.current:
            await msg.reply("Nothing is playing.", quote=True)
            return
        await pl.send_np_message(msg.chat.id)

    # ── /help ─────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("help"))
    async def cmd_help(_, msg: Message):
        sp = "\n/play `spotify:URL` — Spotify track/playlist" if SPOTIFY_ENABLED else ""
        await msg.reply(
            "**🎵 Music Bot Commands**\n\n"
            "/play `<song or URL>` — Search & play\n"
            f"{sp}"
            "/radio `<genre>` — 📻 Endless genre radio\n"
            "/lyrics `[song]` — 📝 Fetch lyrics\n"
            "/history — 📜 Last played tracks\n"
            "/voteskip — 🗳️ Vote to skip current track\n"
            "/np — Now playing + controls\n"
            "/queue — Show queue\n"
            "/pause · /resume · /loop\n"
            "/vol `0–200` — Set volume\n"
            "/skip — Skip _(admin)_\n"
            "/stop — Stop & clear _(admin)_\n",
            quote=True,
        )


# ── Inline button callbacks ───────────────────────────────────────────────────

def register_callbacks(app: Client):

    @app.on_callback_query()
    async def on_button(client, cq):
        chat_id = cq.message.chat.id
        user_id = cq.from_user.id
        data    = cq.data
        st      = state.get(chat_id)

        if data in ("skip", "stop") and ADMIN_ONLY_CMDS:
            if not await is_admin(client, chat_id, user_id):
                await cq.answer("⛔ Admins only.", show_alert=True)
                return

        if data == "pause_resume":
            if st.paused:
                await pl.resume(chat_id)
                await cq.answer("▶️ Resumed")
            else:
                await pl.pause(chat_id)
                await cq.answer("⏸ Paused")
        elif data == "skip":
            title = st.current["title"] if st.current else "?"
            await pl.skip(chat_id)
            await cq.answer(f"⏭ Skipped {title}")
        elif data == "stop":
            await pl.stop(chat_id)
            await cq.answer("⏹ Stopped")
        elif data == "vol_down":
            new_vol = max(0, st.volume - 10)
            await pl.set_volume(chat_id, new_vol)
            await cq.answer(f"🔉 Volume: {new_vol}")
        elif data == "vol_up":
            new_vol = min(200, st.volume + 10)
            await pl.set_volume(chat_id, new_vol)
            await cq.answer(f"🔊 Volume: {new_vol}")
        elif data == "toggle_loop":
            on = await pl.toggle_loop(chat_id)
            await cq.answer(f"🔁 Loop {'ON' if on else 'OFF'}")

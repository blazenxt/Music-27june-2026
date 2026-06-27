"""Telegram VC music bot entry point."""

import asyncio
import logging
import logging.handlers
from pathlib import Path

from pyrogram import Client
from telethon import TelegramClient
from telethon.sessions import StringSession
from pytgcalls import PyTgCalls, filters as call_filters
import config
import player as pl
import commands
import database as db
from state import get as get_state


# ── Logging setup ─────────────────────────────────────────────────────────────

Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "logs/bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        ),
    ],
)
log = logging.getLogger("bot")


# ── Clients ───────────────────────────────────────────────────────────────────

app = Client(
    "music_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)

# PyTgCalls 2.x is currently more reliable with Telethon than Pyrogram.
# SESSION_STRING must be generated with gen_session.py (Telethon StringSession).
userbot = TelegramClient(
    StringSession(config.SESSION_STRING),
    config.API_ID,
    config.API_HASH,
)

call_py = PyTgCalls(userbot)


# ── Wire up ───────────────────────────────────────────────────────────────────

pl.init(app, call_py)
commands.register(app)
commands.register_callbacks(app)
call_py.on_update(call_filters.stream_end())(pl.on_stream_end)


# ── Auto-resume ───────────────────────────────────────────────────────────────

async def _auto_resume():
    """Reload queues from DB and notify groups that were mid-playback."""
    if not config.AUTO_RESUME:
        return
    chat_ids = await db.get_all_active_chats()
    if not chat_ids:
        return
    log.info("Auto-resume: found %d chat(s) with saved queues", len(chat_ids))
    for chat_id in chat_ids:
        try:
            tracks = await db.load_queue(chat_id)
            if not tracks:
                continue
            st = get_state(chat_id)
            st.queue = tracks
            # Restore settings
            vol  = await db.get_setting(chat_id, "volume", config.DEFAULT_VOLUME)
            loop = await db.get_setting(chat_id, "loop", "0")
            st.volume = int(vol)
            st.loop   = bool(int(loop))
            # Notify the group (don't auto-join VC — that requires a live voice chat)
            await app.send_message(
                chat_id,
                f"♻️ Queue restored ({len(tracks)} tracks). "
                "Start a voice chat and use /np to resume.",
            )
            log.info("Restored queue for chat %d (%d tracks)", chat_id, len(tracks))
        except Exception as e:
            log.warning("Auto-resume failed for chat %d: %s", chat_id, e)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    log.info("Initialising database…")
    await db.init_db()

    log.info("Starting userbot…")
    await userbot.start()

    log.info("Starting bot…")
    await app.start()

    log.info("Starting PyTgCalls…")
    await call_py.start()

    me = await app.get_me()
    log.info("✅ Bot running as @%s", me.username)

    await _auto_resume()

    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")

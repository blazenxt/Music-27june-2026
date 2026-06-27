"""Bot API polling fallback for critical owner/bootstrap commands.

Pyrogram should handle the main music bot commands. This module is a safety net
for Railway/MTProto update issues so /start, /myid, /ownerpanel, /gensession and
/restart still work through the normal Bot API getUpdates loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

import aiohttp
from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

import config
import state
import database as db
import player as pl
from helpers import fmt_duration, get_track_info
from pytgcalls.exceptions import NoActiveGroupCall

log = logging.getLogger("bot_api_fallback")
API = f"https://api.telegram.org/bot{config.BOT_TOKEN}"


@dataclass
class SessionFlow:
    client: TelegramClient
    phone: str
    phone_code_hash: str


_flows: dict[int, SessionFlow] = {}


def _is_owner(user_id: int | None) -> bool:
    return bool(user_id and user_id == config.OWNER_ID)


def _main_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🔐 Generate SESSION_STRING", "callback_data": "fb:genses"}],
            [{"text": "🔄 Restart Bot", "callback_data": "fb:restart"}],
        ]
    }


async def _api(session: aiohttp.ClientSession, method: str, **payload):
    async with session.post(f"{API}/{method}", json=payload, timeout=30) as resp:
        text = await resp.text()
        if resp.status != 200:
            log.warning("Bot API %s failed status=%s body=%s", method, resp.status, text[:500])
            return None
        try:
            return await resp.json()
        except Exception:
            log.warning("Bot API %s returned non-json: %s", method, text[:500])
            return None


async def _send(session: aiohttp.ClientSession, chat_id: int, text: str, **extra):
    return await _api(
        session,
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        disable_web_page_preview=True,
        **extra,
    )


async def _answer_cb(session: aiohttp.ClientSession, callback_id: str, text: str = "OK", alert: bool = False):
    return await _api(session, "answerCallbackQuery", callback_query_id=callback_id, text=text, show_alert=alert)


async def _cleanup_flow(user_id: int):
    flow = _flows.pop(user_id, None)
    if flow:
        try:
            await flow.client.disconnect()
        except Exception:
            pass


async def _restart_soon(delay: float = 1.5):
    await asyncio.sleep(delay)
    os.execv(sys.executable, [sys.executable, "bot.py"])


async def _handle_start(session: aiohttp.ClientSession, chat_id: int, user_id: int):
    if _is_owner(user_id):
        await _send(
            session,
            chat_id,
            "✅ *Bot is running!*\n\nYou are owner. Use panel below.",
            reply_markup=_main_keyboard(),
        )
    else:
        await _send(
            session,
            chat_id,
            "✅ *Music bot is online.*\n\n"
            f"Your Telegram user ID: `{user_id}`\n\n"
            "If this is your owner account, set Railway variable:\n"
            f"`OWNER_ID={user_id}`\n\nThen redeploy/restart.",
        )


async def _handle_ownerpanel(session: aiohttp.ClientSession, chat_id: int, user_id: int):
    if not _is_owner(user_id):
        await _send(session, chat_id, "⛔ Owner only. Use /myid and set OWNER_ID in Railway.")
        return
    await _send(
        session,
        chat_id,
        "👑 *Owner Panel*\n\nGenerate the Telethon SESSION_STRING or restart the bot.",
        reply_markup=_main_keyboard(),
    )


async def _start_session_flow(session: aiohttp.ClientSession, chat_id: int, user_id: int, phone: str):
    if not _is_owner(user_id):
        await _send(session, chat_id, "⛔ Owner only.")
        return
    if not phone:
        await _send(session, chat_id, "Usage: `/gensession +919876543210`")
        return

    await _cleanup_flow(user_id)
    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        await client.disconnect()
        await _send(session, chat_id, "❌ Invalid phone number. Use country code, e.g. `+919876543210`.")
        return
    except Exception as e:
        await client.disconnect()
        await _send(session, chat_id, f"❌ Failed to send OTP: `{e}`")
        return

    _flows[user_id] = SessionFlow(client=client, phone=phone, phone_code_hash=sent.phone_code_hash)
    await _send(
        session,
        chat_id,
        "✅ OTP sent on Telegram/SMS.\n\nNow send: `/otp 12345`\n\nIf code has spaces, send without spaces.",
    )


async def _submit_otp(session: aiohttp.ClientSession, chat_id: int, user_id: int, code: str):
    flow = _flows.get(user_id)
    if not flow:
        await _send(session, chat_id, "No active flow. Start with `/gensession +number`.")
        return
    try:
        await flow.client.sign_in(phone=flow.phone, code=code.replace(" ", ""), phone_code_hash=flow.phone_code_hash)
    except SessionPasswordNeededError:
        await _send(session, chat_id, "🔒 2FA enabled. Send: `/2fa your_password`")
        return
    except PhoneCodeInvalidError:
        await _send(session, chat_id, "❌ Invalid OTP. Try again: `/otp 12345`")
        return
    except PhoneCodeExpiredError:
        await _cleanup_flow(user_id)
        await _send(session, chat_id, "❌ OTP expired. Start again with `/gensession +number`.")
        return
    except Exception as e:
        await _cleanup_flow(user_id)
        await _send(session, chat_id, f"❌ Login failed: `{e}`")
        return
    await _finish_session(session, chat_id, user_id)


async def _submit_2fa(session: aiohttp.ClientSession, chat_id: int, user_id: int, password: str):
    flow = _flows.get(user_id)
    if not flow:
        await _send(session, chat_id, "No active flow. Start with `/gensession +number`.")
        return
    try:
        await flow.client.sign_in(password=password)
    except PasswordHashInvalidError:
        await _send(session, chat_id, "❌ Wrong 2FA password. Try again with `/2fa your_password`.")
        return
    except Exception as e:
        await _cleanup_flow(user_id)
        await _send(session, chat_id, f"❌ 2FA login failed: `{e}`")
        return
    await _finish_session(session, chat_id, user_id)


async def _finish_session(session: aiohttp.ClientSession, chat_id: int, user_id: int):
    flow = _flows.get(user_id)
    if not flow:
        return
    session_string = flow.client.session.save()
    await _send(
        session,
        chat_id,
        "✅ *SESSION_STRING generated*\n\n"
        "Copy this into Railway Variables as `SESSION_STRING`, then /restart.\n\n"
        f"`{session_string}`\n\n"
        "⚠️ Keep it private.",
    )
    await _cleanup_flow(user_id)


async def _is_chat_admin(session: aiohttp.ClientSession, chat_id: int, user_id: int) -> bool:
    """Best-effort admin check for fallback commands."""
    if chat_id > 0:  # private chat
        return _is_owner(user_id)
    res = await _api(session, "getChatMember", chat_id=chat_id, user_id=user_id)
    try:
        status = res["result"]["status"]
        return status in ("creator", "administrator")
    except Exception:
        return False


async def _handle_help(session: aiohttp.ClientSession, chat_id: int):
    await _send(
        session,
        chat_id,
        "🎵 *Music Bot Commands*\n\n"
        "/play `<song or url>` - play music\n"
        "/queue - show queue\n"
        "/np - now playing\n"
        "/pause - pause\n"
        "/resume - resume\n"
        "/skip - skip current track\n"
        "/stop - stop and clear queue\n"
        "/loop - toggle loop\n"
        "/vol `0-200` - set volume\n\n"
        "Owner: /ownerpanel",
    )


async def _handle_play(session: aiohttp.ClientSession, chat_id: int, query: str):
    if not query:
        await _send(session, chat_id, "Usage: `/play song name or url`")
        return

    st = state.get(chat_id)
    st.radio_mode = False

    if len(st.queue) >= config.MAX_QUEUE_SIZE:
        await _send(session, chat_id, f"❌ Queue is full ({config.MAX_QUEUE_SIZE} tracks).")
        return

    await _send(session, chat_id, "🔍 Searching…")
    try:
        track = await get_track_info(query)
    except Exception as e:
        await _send(session, chat_id, f"❌ Could not find track: `{e}`")
        return

    st.queue.append(track)
    asyncio.create_task(db.save_queue(chat_id, st.queue))

    if len(st.queue) == 1:
        try:
            await pl.play_current(chat_id, first=True)
            await _send(session, chat_id, f"▶️ Playing: `{track.get('title', 'Unknown')}`")
        except NoActiveGroupCall:
            if st.queue:
                st.queue.pop()
            await _send(session, chat_id, "❌ No active voice chat in this group. Start VC first, then /play again.")
        except Exception as e:
            if st.queue:
                st.queue.pop()
            await _send(session, chat_id, f"❌ Playback failed: `{e}`")
    else:
        await _send(
            session,
            chat_id,
            f"📋 Queued #{len(st.queue)}: `{track.get('title', 'Unknown')}` ({fmt_duration(track.get('duration', 0))})",
        )


async def _handle_queue(session: aiohttp.ClientSession, chat_id: int):
    q = state.get(chat_id).queue
    if not q:
        await _send(session, chat_id, "Queue is empty.")
        return
    lines = []
    for i, t in enumerate(q[:20]):
        icon = "▶️" if i == 0 else f"{i}."
        lines.append(f"{icon} {t.get('title', 'Unknown')} `{fmt_duration(t.get('duration', 0))}`")
    if len(q) > 20:
        lines.append(f"…and {len(q) - 20} more")
    await _send(session, chat_id, "\n".join(lines))


async def _handle_np(session: aiohttp.ClientSession, chat_id: int):
    st = state.get(chat_id)
    if not st.current:
        await _send(session, chat_id, "Nothing is playing.")
        return
    await pl.send_np_message(chat_id)


async def _handle_skip(session: aiohttp.ClientSession, chat_id: int, user_id: int):
    if config.ADMIN_ONLY_CMDS and not await _is_chat_admin(session, chat_id, user_id):
        await _send(session, chat_id, "⛔ Only admins can use this command.")
        return
    st = state.get(chat_id)
    if not st.current:
        await _send(session, chat_id, "Nothing is playing.")
        return
    title = st.current.get("title", "Unknown")
    await pl.skip(chat_id)
    await _send(session, chat_id, f"⏭ Skipped: `{title}`")


async def _handle_stop(session: aiohttp.ClientSession, chat_id: int, user_id: int):
    if config.ADMIN_ONLY_CMDS and not await _is_chat_admin(session, chat_id, user_id):
        await _send(session, chat_id, "⛔ Only admins can use this command.")
        return
    if pl.call_py is None:
        state.clear(chat_id)
        await db.clear_queue(chat_id)
    else:
        await pl.stop(chat_id)
    await _send(session, chat_id, "⏹ Stopped and cleared queue.")


async def _handle_pause(session: aiohttp.ClientSession, chat_id: int):
    if pl.call_py is None:
        await _send(session, chat_id, "❌ Voice userbot is not configured. Set SESSION_STRING and restart.")
        return
    st = state.get(chat_id)
    if not st.current:
        await _send(session, chat_id, "Nothing is playing.")
        return
    await pl.pause(chat_id)
    await _send(session, chat_id, "⏸ Paused.")


async def _handle_resume(session: aiohttp.ClientSession, chat_id: int):
    if pl.call_py is None:
        await _send(session, chat_id, "❌ Voice userbot is not configured. Set SESSION_STRING and restart.")
        return
    st = state.get(chat_id)
    if not st.current:
        await _send(session, chat_id, "Nothing is playing.")
        return
    await pl.resume(chat_id)
    await _send(session, chat_id, "▶️ Resumed.")


async def _handle_loop(session: aiohttp.ClientSession, chat_id: int):
    st = state.get(chat_id)
    st.loop = not st.loop
    await db.set_setting(chat_id, "loop", int(st.loop))
    if pl.call_py is not None:
        await pl.refresh_np(chat_id)
    await _send(session, chat_id, f"🔁 Loop mode: {'ON' if st.loop else 'OFF'}.")


async def _handle_vol(session: aiohttp.ClientSession, chat_id: int, args: str):
    if not args or not args.split()[0].lstrip('-').isdigit():
        await _send(session, chat_id, f"Current volume: `{state.get(chat_id).volume}`. Usage: `/vol 0-200`")
        return
    vol = max(0, min(200, int(args.split()[0])))
    st = state.get(chat_id)
    st.volume = vol
    await db.set_setting(chat_id, "volume", vol)
    if pl.call_py is not None and st.current:
        await pl.set_volume(chat_id, vol)
    await _send(session, chat_id, f"🔊 Volume set to `{vol}`.")


async def _handle_message(session: aiohttp.ClientSession, message: dict[str, Any]):
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}
    chat_id = chat.get("id")
    user_id = from_user.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not user_id or not text.startswith("/"):
        return

    log.info("BotAPI fallback received command text=%r from user_id=%s chat_id=%s", text, user_id, chat_id)
    cmd, _, args = text.partition(" ")
    cmd = cmd.split("@", 1)[0].lower()
    args = args.strip()

    if cmd == "/start":
        await _handle_start(session, chat_id, user_id)
    elif cmd == "/help":
        await _handle_help(session, chat_id)
    elif cmd == "/myid":
        await _send(session, chat_id, f"Your Telegram user ID is:\n`{user_id}`")
    elif cmd in ("/owner", "/ownerpanel"):
        await _handle_ownerpanel(session, chat_id, user_id)
    elif cmd == "/play":
        await _handle_play(session, chat_id, args)
    elif cmd == "/queue":
        await _handle_queue(session, chat_id)
    elif cmd in ("/np", "/nowplaying"):
        await _handle_np(session, chat_id)
    elif cmd == "/skip":
        await _handle_skip(session, chat_id, user_id)
    elif cmd == "/stop":
        await _handle_stop(session, chat_id, user_id)
    elif cmd == "/pause":
        await _handle_pause(session, chat_id)
    elif cmd == "/resume":
        await _handle_resume(session, chat_id)
    elif cmd == "/loop":
        await _handle_loop(session, chat_id)
    elif cmd == "/vol":
        await _handle_vol(session, chat_id, args)
    elif cmd == "/gensession":
        await _start_session_flow(session, chat_id, user_id, args)
    elif cmd == "/otp":
        await _submit_otp(session, chat_id, user_id, args)
    elif cmd in ("/2fa", "/password"):
        await _submit_2fa(session, chat_id, user_id, args)
    elif cmd == "/restart":
        if not _is_owner(user_id):
            await _send(session, chat_id, "⛔ Owner only.")
            return
        await _send(session, chat_id, "🔄 Restarting…")
        asyncio.create_task(_restart_soon())


async def _handle_callback(session: aiohttp.ClientSession, cq: dict[str, Any]):
    data = cq.get("data") or ""
    from_user = cq.get("from") or {}
    user_id = from_user.get("id")
    msg = cq.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    callback_id = cq.get("id")
    if not data.startswith("fb:") or not chat_id or not user_id or not callback_id:
        return

    if not _is_owner(user_id):
        await _answer_cb(session, callback_id, "Owner only", True)
        return

    if data == "fb:genses":
        await _answer_cb(session, callback_id, "Send /gensession +number")
        await _send(session, chat_id, "Send `/gensession +<countrycode><number>`\nExample: `/gensession +919876543210`")
    elif data == "fb:restart":
        await _answer_cb(session, callback_id, "Restarting…")
        await _send(session, chat_id, "🔄 Restarting bot…")
        asyncio.create_task(_restart_soon())


async def run():
    """Run fallback polling forever. Safe to start as a background task."""
    offset = 0
    async with aiohttp.ClientSession() as session:
        # Make sure old webhooks do not block getUpdates.
        await _api(session, "deleteWebhook", drop_pending_updates=False)
        me = await _api(session, "getMe")
        if me and me.get("ok"):
            log.info("Bot API fallback polling active as @%s", me["result"].get("username"))

        while True:
            try:
                res = await _api(
                    session,
                    "getUpdates",
                    offset=offset,
                    timeout=25,
                    allowed_updates=["message", "callback_query"],
                )
                if not res or not res.get("ok"):
                    await asyncio.sleep(3)
                    continue
                for upd in res.get("result", []):
                    offset = max(offset, upd.get("update_id", 0) + 1)
                    if "message" in upd:
                        await _handle_message(session, upd["message"])
                    elif "callback_query" in upd:
                        await _handle_callback(session, upd["callback_query"])
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Bot API fallback polling error: %s", e)
                await asyncio.sleep(3)

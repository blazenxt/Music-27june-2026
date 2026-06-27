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
    elif cmd == "/myid":
        await _send(session, chat_id, f"Your Telegram user ID is:\n`{user_id}`")
    elif cmd in ("/owner", "/ownerpanel"):
        await _handle_ownerpanel(session, chat_id, user_id)
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

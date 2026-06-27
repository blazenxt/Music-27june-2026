"""Owner-only tools: in-bot Telethon session generation and restart controls."""

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
)
from telethon.sessions import StringSession

import config

_verified_runtime_owners: set[int] = set()


@dataclass
class SessionFlow:
    client: TelegramClient
    phone: str
    phone_code_hash: str
    status_message_id: int


_flows: dict[int, SessionFlow] = {}


def _is_owner(user_id: Optional[int]) -> bool:
    return bool(user_id and (user_id == config.OWNER_ID or user_id in _verified_runtime_owners))


def _norm_phone(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def _owner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Generate SESSION_STRING", callback_data="owner:genses")],
        [InlineKeyboardButton("🔄 Restart Bot", callback_data="owner:restart")],
    ])


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel session generation", callback_data="owner:cancel_genses")],
    ])


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


def register(app: Client):
    @app.on_message(filters.command("start"))
    async def start_cmd(_, msg: Message):
        user_id = msg.from_user.id if msg.from_user else 0
        if _is_owner(user_id):
            await msg.reply(
                "✅ **Bot is running!**\n\n"
                "You are verified as owner. Use the panel below.",
                reply_markup=_owner_keyboard(),
                quote=True,
            )
        else:
            await msg.reply(
                "✅ **Music bot is online.**\n\n"
                f"Your Telegram user ID: `{user_id}`\n\n"
                "Owner tools are locked. If you are the owner, use `/myid` and set `OWNER_ID` in Railway, "
                "or use `/verifyowner` and share the owner phone contact.",
                quote=True,
            )

    @app.on_message(filters.command("myid"))
    async def myid_cmd(_, msg: Message):
        user_id = msg.from_user.id if msg.from_user else 0
        await msg.reply(f"Your Telegram user ID is:\n`{user_id}`", quote=True)

    @app.on_message(filters.command("verifyowner"))
    async def verify_owner_cmd(_, msg: Message):
        await msg.reply(
            "To verify owner access, tap the button below and share the Telegram contact for the owner number.\n\n"
            "This is only needed if `OWNER_ID` is not your actual Telegram user ID.",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📱 Share owner contact", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
            quote=True,
        )

    @app.on_message(filters.contact)
    async def owner_contact(_, msg: Message):
        if not msg.from_user or not msg.contact:
            return
        owner_phone = _norm_phone(str(getattr(config, "OWNER_PHONE", "8708907310")))
        sent_phone = _norm_phone(msg.contact.phone_number)
        # Telegram sets contact.user_id only when user shares their own Telegram contact.
        is_self_contact = msg.contact.user_id == msg.from_user.id
        if is_self_contact and sent_phone.endswith(owner_phone):
            _verified_runtime_owners.add(msg.from_user.id)
            await msg.reply(
                "✅ Owner verified for this running container.\n\nUse /ownerpanel now.",
                reply_markup=ReplyKeyboardRemove(),
                quote=True,
            )
        else:
            await msg.reply(
                "❌ Owner verification failed. Share your own Telegram contact linked to the owner phone number.",
                reply_markup=ReplyKeyboardRemove(),
                quote=True,
            )

    @app.on_message(filters.command(["owner", "ownerpanel"]))
    async def owner_panel(_, msg: Message):
        if not _is_owner(msg.from_user.id if msg.from_user else None):
            await msg.reply("⛔ This panel is owner-only.", quote=True)
            return
        await msg.reply(
            "👑 **Owner Panel**\n\n"
            "Use this to generate a Telethon `SESSION_STRING` or restart the bot.",
            reply_markup=_owner_keyboard(),
            quote=True,
        )

    @app.on_message(filters.command("restart"))
    async def restart_cmd(_, msg: Message):
        if not _is_owner(msg.from_user.id if msg.from_user else None):
            await msg.reply("⛔ Owner only.", quote=True)
            return
        await msg.reply("🔄 Restarting…", quote=True)
        asyncio.create_task(_restart_soon())

    @app.on_message(filters.command("gensession"))
    async def gensession_cmd(_, msg: Message):
        if not _is_owner(msg.from_user.id if msg.from_user else None):
            await msg.reply("⛔ Owner only.", quote=True)
            return
        await _cleanup_flow(msg.from_user.id)
        await msg.reply(
            "🔐 **SESSION_STRING Generator**\n\n"
            "Send your phone number with country code. Example:\n"
            "`/gensession +919876543210`\n\n"
            "Flow: phone → OTP → 2FA password if enabled.\n"
            "You can also press the button in /ownerpanel.",
            reply_markup=_cancel_keyboard(),
            quote=True,
        )

        args = " ".join(msg.command[1:]).strip()
        if args:
            await _start_session_flow(msg, args)

    @app.on_message(filters.command("otp"))
    async def otp_cmd(_, msg: Message):
        if not _is_owner(msg.from_user.id if msg.from_user else None):
            return
        code = " ".join(msg.command[1:]).strip().replace(" ", "")
        if not code:
            await msg.reply("Usage: `/otp 12345`", quote=True)
            return
        await _submit_otp(msg, code)

    @app.on_message(filters.command(["2fa", "password"], prefixes=["/", ".", "!"]))
    async def twofa_cmd(_, msg: Message):
        if not _is_owner(msg.from_user.id if msg.from_user else None):
            return
        password = " ".join(msg.command[1:]).strip()
        if not password:
            await msg.reply("Usage: `/2fa your_password`", quote=True)
            return
        await _submit_2fa(msg, password)

    @app.on_callback_query(filters.regex(r"^owner:"))
    async def owner_callback(_, cq: CallbackQuery):
        if not _is_owner(cq.from_user.id if cq.from_user else None):
            await cq.answer("⛔ Owner only.", show_alert=True)
            return

        if cq.data == "owner:genses":
            await cq.message.reply(
                "🔐 Send `/gensession +<countrycode><number>` to begin.\n"
                "Example: `/gensession +919876543210`",
                reply_markup=_cancel_keyboard(),
                quote=True,
            )
            await cq.answer("Session generator opened")
        elif cq.data == "owner:restart":
            await cq.answer("Restarting…")
            await cq.message.reply("🔄 Restarting bot…")
            asyncio.create_task(_restart_soon())
        elif cq.data == "owner:cancel_genses":
            await _cleanup_flow(cq.from_user.id)
            await cq.answer("Cancelled")
            await cq.message.reply("❌ Session generation cancelled.")


async def _start_session_flow(msg: Message, phone: str):
    user_id = msg.from_user.id
    await _cleanup_flow(user_id)

    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        await client.disconnect()
        await msg.reply("❌ Invalid phone number. Use country code, e.g. `+919876543210`.", quote=True)
        return
    except Exception as e:
        await client.disconnect()
        await msg.reply(f"❌ Failed to send OTP: `{e}`", quote=True)
        return

    status = await msg.reply(
        "✅ OTP sent on Telegram/SMS.\n\n"
        "Now send:\n"
        "`/otp 12345`\n\n"
        "If Telegram shows the code as `1 2 3 4 5`, send it without spaces.",
        reply_markup=_cancel_keyboard(),
        quote=True,
    )
    _flows[user_id] = SessionFlow(
        client=client,
        phone=phone,
        phone_code_hash=sent.phone_code_hash,
        status_message_id=status.id,
    )


async def _submit_otp(msg: Message, code: str):
    user_id = msg.from_user.id
    flow = _flows.get(user_id)
    if not flow:
        await msg.reply("No active session flow. Start with `/gensession +number`.", quote=True)
        return

    try:
        await flow.client.sign_in(
            phone=flow.phone,
            code=code,
            phone_code_hash=flow.phone_code_hash,
        )
    except SessionPasswordNeededError:
        await msg.reply(
            "🔒 This account has 2FA enabled.\n\n"
            "Send your password with:\n"
            "`/2fa your_password`",
            reply_markup=_cancel_keyboard(),
            quote=True,
        )
        return
    except PhoneCodeInvalidError:
        await msg.reply("❌ Invalid OTP. Try again: `/otp 12345`", quote=True)
        return
    except PhoneCodeExpiredError:
        await _cleanup_flow(user_id)
        await msg.reply("❌ OTP expired. Start again with `/gensession +number`.", quote=True)
        return
    except Exception as e:
        await _cleanup_flow(user_id)
        await msg.reply(f"❌ Login failed: `{e}`", quote=True)
        return

    await _finish_session(msg)


async def _submit_2fa(msg: Message, password: str):
    user_id = msg.from_user.id
    flow = _flows.get(user_id)
    if not flow:
        await msg.reply("No active session flow. Start with `/gensession +number`.", quote=True)
        return

    try:
        await flow.client.sign_in(password=password)
    except PasswordHashInvalidError:
        await msg.reply("❌ Wrong 2FA password. Try again with `/2fa your_password`.", quote=True)
        return
    except Exception as e:
        await _cleanup_flow(user_id)
        await msg.reply(f"❌ 2FA login failed: `{e}`", quote=True)
        return

    await _finish_session(msg)


async def _finish_session(msg: Message):
    user_id = msg.from_user.id
    flow = _flows.get(user_id)
    if not flow:
        return

    session_string = flow.client.session.save()
    await msg.reply(
        "✅ **SESSION_STRING generated**\n\n"
        "Copy this value into Railway Variables as `SESSION_STRING`, then use /restart.\n\n"
        f"`{session_string}`\n\n"
        "⚠️ Keep it private. Anyone with this string can access that Telegram account session.",
        quote=True,
    )
    await _cleanup_flow(user_id)

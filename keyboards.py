"""
keyboards.py — Inline keyboard layouts for the now-playing message.
"""

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def player_keyboard(paused: bool = False, loop: bool = False) -> InlineKeyboardMarkup:
    pause_label = "▶️ Resume" if paused else "⏸ Pause"
    loop_label  = "🔁 Loop ON" if loop else "🔁 Loop OFF"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(pause_label, callback_data="pause_resume"),
            InlineKeyboardButton("⏭ Skip",   callback_data="skip"),
            InlineKeyboardButton("⏹ Stop",   callback_data="stop"),
        ],
        [
            InlineKeyboardButton("🔉 Vol -10", callback_data="vol_down"),
            InlineKeyboardButton(loop_label,   callback_data="toggle_loop"),
            InlineKeyboardButton("🔊 Vol +10", callback_data="vol_up"),
        ],
    ])

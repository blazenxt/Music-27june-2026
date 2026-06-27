"""
database.py — Async SQLite persistence.
Stores: per-chat queue, playback history, group settings, vote-skip state.

Tables
------
queue    : (chat_id, position, title, url, duration, thumbnail, webpage_url, query)
history  : (id, chat_id, title, webpage_url, duration, played_at)
settings : (chat_id, key, value)
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import aiosqlite

log = logging.getLogger(__name__)

DB_PATH = Path("data/musicbot.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS queue (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                position    INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                url         TEXT,
                duration    INTEGER DEFAULT 0,
                thumbnail   TEXT    DEFAULT '',
                webpage_url TEXT    DEFAULT '',
                query       TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                title       TEXT    NOT NULL,
                webpage_url TEXT    DEFAULT '',
                duration    INTEGER DEFAULT 0,
                played_at   REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                chat_id     INTEGER NOT NULL,
                key         TEXT    NOT NULL,
                value       TEXT    NOT NULL,
                PRIMARY KEY (chat_id, key)
            );

            CREATE INDEX IF NOT EXISTS idx_queue_chat   ON queue   (chat_id, position);
            CREATE INDEX IF NOT EXISTS idx_history_chat ON history (chat_id, played_at DESC);
        """)
        await db.commit()
    log.info("Database ready at %s", DB_PATH)


# ── Queue ─────────────────────────────────────────────────────────────────────

async def save_queue(chat_id: int, tracks: list[dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM queue WHERE chat_id = ?", (chat_id,))
        for pos, t in enumerate(tracks):
            await db.execute(
                """INSERT INTO queue
                   (chat_id, position, title, url, duration, thumbnail, webpage_url, query)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    chat_id, pos,
                    t.get("title", ""),
                    t.get("url"),
                    t.get("duration", 0),
                    t.get("thumbnail", ""),
                    t.get("webpage_url", ""),
                    t.get("_yt_query") or t.get("_query", ""),
                ),
            )
        await db.commit()


async def load_queue(chat_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM queue WHERE chat_id = ? ORDER BY position",
            (chat_id,),
        )
        rows = await cursor.fetchall()
    return [
        {
            "title":       r["title"],
            "url":         r["url"],
            "duration":    r["duration"],
            "thumbnail":   r["thumbnail"],
            "webpage_url": r["webpage_url"],
            "_yt_query":   r["query"],
        }
        for r in rows
    ]


async def clear_queue(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM queue WHERE chat_id = ?", (chat_id,))
        await db.commit()


# ── History ───────────────────────────────────────────────────────────────────

async def push_history(chat_id: int, track: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO history (chat_id, title, webpage_url, duration, played_at)
               VALUES (?,?,?,?,?)""",
            (
                chat_id,
                track.get("title", ""),
                track.get("webpage_url", ""),
                track.get("duration", 0),
                time.time(),
            ),
        )
        # Keep only last 100 entries per chat
        await db.execute(
            """DELETE FROM history WHERE chat_id = ? AND id NOT IN (
               SELECT id FROM history WHERE chat_id = ?
               ORDER BY played_at DESC LIMIT 100)""",
            (chat_id, chat_id),
        )
        await db.commit()


async def get_history(chat_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT title, webpage_url, duration, played_at
               FROM history WHERE chat_id = ?
               ORDER BY played_at DESC LIMIT ?""",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_setting(chat_id: int, key: str, default=None) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
            (chat_id, key),
        )
        row = await cursor.fetchone()
    return row[0] if row else default


async def set_setting(chat_id: int, key: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (chat_id, key, value) VALUES (?,?,?)",
            (chat_id, key, str(value)),
        )
        await db.commit()


async def get_all_active_chats() -> list[int]:
    """Return chat_ids that have a saved queue (for auto-resume)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT chat_id FROM queue"
        )
        rows = await cursor.fetchall()
    return [r[0] for r in rows]

"""
state.py — Per-group playback state (v3).
Adds: radio_mode flag, radio_genre, DB sync hooks.
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChatState:
    queue:            list[dict]    = field(default_factory=list)
    loop:             bool          = False
    volume:           int           = 100
    paused:           bool          = False
    started_at:       float         = 0.0
    pause_at:         float         = 0.0
    elapsed_at_pause: float         = 0.0
    np_message_id:    Optional[int] = None

    # Radio mode
    radio_mode:       bool          = False
    radio_genre:      str           = ""

    # ── Current track shortcuts ─────────────────────────────────────────────

    @property
    def current(self) -> Optional[dict]:
        return self.queue[0] if self.queue else None

    @property
    def elapsed(self) -> float:
        if not self.queue:
            return 0.0
        if self.paused:
            return self.elapsed_at_pause
        if self.started_at == 0.0:
            return 0.0
        return time.time() - self.started_at + self.elapsed_at_pause

    def mark_started(self):
        self.started_at       = time.time()
        self.elapsed_at_pause = 0.0
        self.paused           = False
        self.pause_at         = 0.0

    def mark_paused(self):
        if not self.paused:
            self.elapsed_at_pause += time.time() - self.started_at
            self.paused            = True

    def mark_resumed(self):
        if self.paused:
            self.started_at = time.time()
            self.paused     = False

    def advance(self):
        """Pop the front of queue (or loop it)."""
        if not self.queue:
            return
        if self.loop:
            self.queue.append(self.queue.pop(0))
        else:
            self.queue.pop(0)
        self.mark_started()


# ── Global registry ──────────────────────────────────────────────────────────

_states: dict[int, ChatState] = {}


def get(chat_id: int) -> ChatState:
    if chat_id not in _states:
        _states[chat_id] = ChatState()
    return _states[chat_id]


def clear(chat_id: int):
    _states.pop(chat_id, None)


def all_active() -> list[int]:
    return list(_states.keys())

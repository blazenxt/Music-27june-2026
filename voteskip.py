"""
voteskip.py — Democratic skip voting.

A skip passes when ⌈online_members × THRESHOLD⌉ votes are cast.
Votes reset when the track changes.
"""

import math
from config import VOTESKIP_THRESHOLD   # e.g. 0.5 → majority

# chat_id -> set of user_ids who voted to skip this track
_votes: dict[int, set[int]] = {}


def add_vote(chat_id: int, user_id: int) -> bool:
    """Register a vote. Returns True if this user is a new voter."""
    if chat_id not in _votes:
        _votes[chat_id] = set()
    if user_id in _votes[chat_id]:
        return False
    _votes[chat_id].add(user_id)
    return True


def vote_count(chat_id: int) -> int:
    return len(_votes.get(chat_id, set()))


def reset(chat_id: int):
    _votes.pop(chat_id, None)


def needed(member_count: int) -> int:
    """How many votes are needed to pass, given member_count."""
    return max(1, math.ceil(member_count * VOTESKIP_THRESHOLD))


async def get_member_count(client, chat_id: int) -> int:
    try:
        count = await client.get_chat_members_count(chat_id)
        # Subtract bots (rough: subtract 2 for bot + userbot)
        return max(1, count - 2)
    except Exception:
        return 3   # safe fallback

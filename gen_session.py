"""Generate a Telethon SESSION_STRING for the voice-chat userbot.

Run locally, then copy the printed SESSION_STRING into Railway variables.
Never commit the generated session string.
"""

import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession


def main():
    api_id = int(os.getenv("API_ID") or input("API_ID: ").strip())
    api_hash = os.getenv("API_HASH") or input("API_HASH: ").strip()

    print("\nLogin with the Telegram user account that will join voice chats.")
    with TelegramClient(StringSession(), api_id, api_hash) as client:
        print("\nSESSION_STRING:\n")
        print(client.session.save())
        print("\nAdd this value to Railway as SESSION_STRING.")


if __name__ == "__main__":
    main()

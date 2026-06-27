# 🎵 Telegram VC Music Bot

Telegram group voice-chat music bot with YouTube search/URLs, Spotify links via `spotdl`, radio mode, lyrics, history, queue controls, vote-skip and inline player buttons.

## Features

- `/play <song or URL>` — YouTube search/URL or Spotify track/playlist/album/artist URL
- `/radio <genre>` — genre radio with Spotify playlist preference and YouTube fallback
- `/lyrics [song]` — lyrics lookup
- `/history` — recently played tracks
- `/voteskip` — democratic skip voting
- `/np`, `/queue`, `/pause`, `/resume`, `/loop`, `/vol`, `/skip`, `/stop`
- SQLite queue/history persistence
- YouTube cookies support for bot-detection issues

## Required environment variables

Create these variables in Railway or a local `.env` file:

```env
API_ID=12345678
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
SESSION_STRING=your_pyrogram_session_string
```

Optional:

```env
YT_COOKIES_FILE=cookies/youtube.txt
LOG_CHANNEL_ID=0
AUTO_RESUME=true
ADMIN_ONLY_CMDS=true
RADIO_PREFER_SPOTIFY=true
```

## Generate `SESSION_STRING`

Run locally, not on Railway. This generates a **Telethon StringSession** for the voice userbot:

```bash
pip install -r requirements.txt
python gen_session.py
```

Login with the Telegram user account that will join voice chats. Copy the printed session string into Railway as `SESSION_STRING`.


## Owner-only controls

Only the Telegram user ID in `OWNER_ID` can use these commands/buttons. Default:

```env
OWNER_ID=8708907310
```

Commands:

- `/ownerpanel` — shows buttons for session generation and restart
- `/gensession +919876543210` — generate the Telethon `SESSION_STRING` through bot chat
- `/otp 12345` — submit login OTP
- `/2fa your_password` — submit 2FA password if Telegram asks for it
- `/restart` — restart the bot process

After `/gensession` prints the string, paste it into Railway Variables as `SESSION_STRING`, then press restart or run `/restart`.

## Deploy on Railway

1. Push this repo to GitHub.
2. In Railway, create **New Project → Deploy from GitHub repo**.
3. Add the required environment variables above.
4. Railway will use `nixpacks.toml` to install Python and `ffmpeg`.
5. Use the worker/start command:

```bash
python bot.py
```

This repo includes both `Procfile` and `nixpacks.toml` for Railway deployment.

## Local run

```bash
cp .env.example .env
pip install -r requirements.txt
python gen_session.py  # only once, to get SESSION_STRING
python bot.py
```

You also need `ffmpeg` installed locally:

```bash
sudo apt update && sudo apt install -y ffmpeg
```


## Spotify-first playback mode

By default, normal `/play song name` searches Spotify first using `spotdl` for better metadata and matching, then resolves the selected track to a playable stream. YouTube is used only as the stream provider/fallback because Telegram voice chats need a direct audio stream and Spotify does not expose public direct stream URLs.

```env
PREFER_SPOTIFY_SEARCH=true
```

Use full Spotify links for best results:

```txt
/play https://open.spotify.com/track/...
/play https://open.spotify.com/playlist/...
```

Plain searches also prefer Spotify now:

```txt
/play bairan
/play siya ram
```

## YouTube cookies

If YouTube returns “Sign in to confirm you're not a bot”, export cookies and save them as:

```txt
cookies/youtube.txt
```

See `cookies/HOW_TO_GET_COOKIES.md`.

Real cookie files are ignored by git.

## Notes

- The bot account handles commands.
- The userbot session joins and streams into voice chats. Generate `SESSION_STRING` with this repo's `gen_session.py`; older Pyrogram session strings are not compatible because playback uses Telethon for voice calls.
- Start a group voice chat before using `/play`.
- Spotify playback is resolved to YouTube audio; Spotify Premium is not required.

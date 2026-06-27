# 🎵 Telegram VC Music Bot v4

Spotify-first music bot with YouTube cookies support.

## What's new in v4

| Feature | v3 | v4 |
|---|---|---|
| 🎵 `/radio` via Spotify playlists | ❌ YT only | ✅ Spotify editorial playlists |
| 🎯 Smart Spotify→YT matching | ❌ title search only | ✅ duration-aware, picks closest match |
| 🍪 YouTube cookies support | ❌ | ✅ fixes bot-detection errors |
| 🎤 `/play spotify:artist/...` | ❌ | ✅ artist top tracks |
| 🎨 Rich Spotify metadata | ❌ | ✅ artist, album, thumbnail from Spotify |
| 📻 Spotify genre playlists | ❌ | ✅ 14 curated Spotify playlists |

---

## Setup

### 1. Install
```bash
pip install -r requirements.txt
```
> Also requires ffmpeg: `sudo apt install ffmpeg`

### 2. Spotify credentials
1. Go to https://developer.spotify.com/dashboard
2. Create an app → copy **Client ID** and **Client Secret**
3. Add to `.env`

### 3. YouTube cookies (fixes bot-detection)
See `cookies/HOW_TO_GET_COOKIES.md` for full instructions. Short version:
- Install "Get cookies.txt LOCALLY" browser extension
- Log in to YouTube
- Export → save as `cookies/youtube.txt`

### 4. Configure
```bash
cp .env.example .env
python gen_session.py   # generate SESSION_STRING once
```

### 5. Run
```bash
python bot.py
```

---

## Commands

| Command | Description |
|---|---|
| `/play <song>` | YouTube search |
| `/play <spotify track URL>` | Spotify track → YouTube stream |
| `/play <spotify playlist URL>` | Queue full Spotify playlist |
| `/play <spotify album URL>` | Queue full album |
| `/play <spotify artist URL>` | Queue artist's top 10 tracks |
| `/radio <genre>` | Endless Spotify editorial radio |
| `/lyrics [song]` | Fetch lyrics |
| `/history` | Last played tracks |
| `/voteskip` | Vote to skip |
| `/np` | Now playing + controls |
| `/queue` | Show queue |
| `/pause` / `/resume` / `/loop` | Playback control |
| `/vol 0–200` | Set volume |
| `/skip` | Skip _(admin)_ |
| `/stop` | Stop & clear _(admin)_ |

---

## Radio genres (Spotify playlists)

`lofi` · `hiphop` · `pop` · `rock` · `electronic` · `jazz` · `classical` · `rnb` · `metal` · `country` · `kpop` · `anime` · `workout` · `sleep`

Custom genres work too via YouTube fallback: `/radio bhangra`, `/radio phonk`

---

## How Spotify → YouTube works

```
/play spotify link
    ↓
spotipy fetches: title, artist, album, duration_ms, thumbnail
    ↓
yt-dlp searches YouTube with: "{artist} - {title} official audio"
    ↓
Top 5 results compared by duration (picks closest match)
    ↓
Stream URL extracted with cookies → played in VC
```

Duration matching prevents getting live versions, covers, or wrong songs.

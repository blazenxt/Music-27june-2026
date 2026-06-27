# How to Get YouTube cookies.txt

YouTube cookies fix these errors:
- "Sign in to confirm you're not a bot"
- Age-restricted videos blocked
- Some region-locked content

---

## Method 1: Browser Extension (Easiest)

1. Install **"Get cookies.txt LOCALLY"** extension:
   - Chrome: https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
   - Firefox: https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/

2. Open **https://youtube.com** and make sure you're **logged in**

3. Click the extension icon → **Export** → save as `youtube.txt`

4. Place the file at: `cookies/youtube.txt` (next to bot.py)

---

## Method 2: yt-dlp CLI (If you have yt-dlp installed locally)

```bash
# Chrome
yt-dlp --cookies-from-browser chrome --cookies cookies/youtube.txt "https://youtube.com"

# Firefox  
yt-dlp --cookies-from-browser firefox --cookies cookies/youtube.txt "https://youtube.com"
```

---

## Verify it works

```bash
yt-dlp --cookies cookies/youtube.txt "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --simulate
```

If no error → cookies are working!

---

## Notes

- Cookies expire after some weeks — regenerate if errors return
- Use a regular Google account (not your main one, just to be safe)
- The bot reads `cookies/youtube.txt` automatically on startup
- You can change the path in `.env`: `YT_COOKIES_FILE=path/to/cookies.txt`

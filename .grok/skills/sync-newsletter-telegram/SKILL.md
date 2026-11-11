---
name: sync-newsletter-telegram
description: Sync news_letter/index.html with its folders, build PDFs for new reviews, and post subscriber-only download links to @dpgl_news. Use for the daily newsletter job or when asked to update the VPK catalog.
---

# Sync newsletter catalog and post PDF links

Root: `C:\to_sync\prog\GITHUB\dpgl_news\news_letter`
Channel: `@dpgl_news` (fallback `-1004402580262`). Bot that delivers files: `@dpgl77_bot`.

## Steps

1. Run `python "C:\to_sync\prog\GITHUB\dpgl_news\news_letter\sync_catalog.py"`.
2. Stop when the script prints `pending: 0`.
3. Read `news_letter\_private\pending_telegram.json`. For each object, one at a time, `TELEGRAM_SEND_MESSAGE`:
   - `chat_id`: `@dpgl_news`
   - `parse_mode`: `HTML`
   - `disable_web_page_preview`: true
   - `text`: that object's `text`, unchanged
   Wait for `ok: true`. On HTTP 429, wait `retry_after` and retry that object only.
4. Do not send the PDF into the channel and do not post a public file URL. The link in `text` opens the bot. `telegram_gate.py` checks membership of `@dpgl_news` and only then sends the file. The gate reads the bot token from `news_letter\_private\bot_token.txt` or `TELEGRAM_BOT_TOKEN`. Do not create that file from chat and do not print the token.
5. After each successful send run `python "C:\to_sync\prog\GITHUB\dpgl_news\news_letter\sync_catalog.py" --mark-posted <token> <message_id>`.

Composio: `COMPOSIO_SEARCH_TOOLS` for sending a Telegram channel message, then continue only if the telegram connection is ACTIVE. Do not ask to confirm the channel.

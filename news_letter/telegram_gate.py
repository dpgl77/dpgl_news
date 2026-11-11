# -*- coding: utf-8 -*-
"""Give a newsletter PDF only to subscribers of @dpgl_news.

The channel post contains https://t.me/dpgl77_bot?start=nl_<token>.
This process reads that /start, checks getChatMember, then sends the file in a private chat.
"""
import json
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "_private"
STATE_PATH = PRIVATE / "catalog.json"
TOKEN_PATH = PRIVATE / "bot_token.txt"
OFFSET_PATH = PRIVATE / "updates_offset.txt"
LOCK_PATH = PRIVATE / "gate.lock"
CHANNEL = "@dpgl_news"
SUBSCRIBED = {"creator", "administrator", "member"}


def token():
    env = os_environ_token()
    if env:
        return env
    if not TOKEN_PATH.exists():
        return ""
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def os_environ_token():
    import os
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def api(bot_token, method, payload=None, timeout=30):
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or method)
    return body["result"]


def send_document(bot_token, chat_id, pdf_path, caption):
    boundary = "dpgl" + uuid.uuid4().hex
    file_bytes = Path(pdf_path).read_bytes()
    filename = Path(pdf_path).name
    parts = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption), ("parse_mode", "HTML")):
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8")
    body = b"".join(parts) + head + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description") or "sendDocument")


def subscribed(bot_token, user_id):
    member = api(bot_token, "getChatMember", {"chat_id": CHANNEL, "user_id": user_id})
    status = member.get("status")
    if status in SUBSCRIBED:
        return True
    return status == "restricted" and bool(member.get("is_member"))


def lookup(start_token):
    if not STATE_PATH.exists():
        return None
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    for record in state.get("files", {}).values():
        if record.get("token") == start_token and Path(record.get("pdf", "")).exists():
            return record
    return None


def handle(bot_token, message):
    text = message.get("text") or ""
    if not text.startswith("/start"):
        return
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    if chat.get("type") != "private" or "id" not in user:
        return
    payload = text.split(maxsplit=1)[1].strip() if " " in text else ""
    if not payload.startswith("nl_"):
        api(bot_token, "sendMessage", {
            "chat_id": chat["id"],
            "text": "Откройте ссылку «Скачать PDF» из канала @dpgl_news.",
        })
        return
    record = lookup(payload[3:])
    if record is None:
        api(bot_token, "sendMessage", {
            "chat_id": chat["id"],
            "text": "Этот обзор не найден. Откройте свежую ссылку из канала @dpgl_news.",
        })
        return
    if not subscribed(bot_token, user["id"]):
        api(bot_token, "sendMessage", {
            "chat_id": chat["id"],
            "text": "PDF доступен только подписчикам @dpgl_news. Подпишитесь: https://t.me/dpgl_news и снова откройте ссылку из канала.",
        })
        return
    caption = f"<b>{record['title']}</b>\n{record['date_label']}"
    send_document(bot_token, chat["id"], record["pdf"], caption[:1024])


def main():
    bot_token = token()
    if not bot_token:
        print("gate: waiting for news_letter/_private/bot_token.txt or TELEGRAM_BOT_TOKEN")
        return
    PRIVATE.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists() and time.time() - LOCK_PATH.stat().st_mtime > 600:
        LOCK_PATH.unlink()
    try:
        LOCK_PATH.open("x").close()
    except FileExistsError:
        print("gate: already running")
        return
    try:
        offset = int(OFFSET_PATH.read_text(encoding="utf-8").strip()) if OFFSET_PATH.exists() else 0
        updates = api(bot_token, "getUpdates", {
            "offset": offset,
            "timeout": 0,
            "allowed_updates": json.dumps(["message"]),
        })
        for update in updates:
            offset = max(offset, int(update["update_id"]) + 1)
            message = update.get("message")
            if message:
                handle(bot_token, message)
        if updates:
            OFFSET_PATH.write_text(str(offset), encoding="utf-8")
        print(f"gate: updates {len(updates)}")
    finally:
        LOCK_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        text = str(exc)
        secret = token()
        if secret:
            text = text.replace(secret, "***")
        print(f"gate error: {text}")
        raise SystemExit(1)

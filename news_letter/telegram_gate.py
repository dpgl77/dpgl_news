# -*- coding: utf-8 -*-
"""Give a newsletter PDF only to subscribers of @dpgl_news.

The channel post contains https://t.me/dpgl77_bot?start=nl_<token>.
This process reads that /start, checks getChatMember, then sends the file in a private chat.

Before sendDocument the PDF is watermarked in memory (the file in _private
is never modified): a faint DPGL77 shield on every page and a footer with
the site URL plus «специально для @username (ID …) · DD.MM.YYYY».
Needs pymupdf:  pip install pymupdf
"""
import os
import json
import time
import uuid
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "_private"
STATE_PATH = PRIVATE / "catalog.json"
TOKEN_PATH = PRIVATE / "bot_token.txt"
OFFSET_PATH = PRIVATE / "updates_offset.txt"
LOCK_PATH = PRIVATE / "gate.lock"
CHANNEL = "@dpgl_news"
SUBSCRIBED = {"creator", "administrator", "member"}
SITE_URL = "https://dpgl77.github.io/dpgl_news/"
WATERMARK_OPACITY = 0.08
# Telegram Bot API never sends a user's phone number with a normal message.
# A phone can appear only if the user taps a custom keyboard «request_contact»
# button and shares the contact. The footer therefore uses @username, or the
# first+last name, or just the numeric Telegram ID.


def token():
    env = os_environ_token()
    if env:
        return env
    if not TOKEN_PATH.exists():
        return ""
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def os_environ_token():
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


# ---------------------------------------------------------------- watermark
def recipient_label(user, when=None):
    """Footer line: специально для @name (ID 123) · DD.MM.YYYY."""
    user = user or {}
    user_id = user.get("id", "")
    username = (user.get("username") or "").strip().lstrip("@")
    first = (user.get("first_name") or "").strip()
    last = (user.get("last_name") or "").strip()
    full = " ".join(part for part in (first, last) if part)
    date = (when or datetime.now()).strftime("%d.%m.%Y")
    if username:
        who = f"@{username}"
    elif full:
        who = full
    else:
        who = None
    if who:
        return f"специально для {who} (ID {user_id}) · {date}"
    return f"специально для ID {user_id} · {date}"


def find_cyrillic_font():
    """Arial on Windows, DejaVu/Liberation on Linux, or a TTF next to this script."""
    windir = Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows")
    candidates = [
        ROOT / "DejaVuSans.ttf",
        PRIVATE / "DejaVuSans.ttf",
        windir / "Fonts" / "arial.ttf",
        windir / "Fonts" / "Arial.ttf",
        windir / "Fonts" / "arialuni.ttf",
        windir / "Fonts" / "segoeui.ttf",
        windir / "Fonts" / "calibri.ttf",
        windir / "Fonts" / "tahoma.ttf",
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def find_emblem():
    repo = ROOT.parent
    for path in (
        repo / "img" / "dpgl77-shield-large.png",
        repo / "img" / "dpgl77-shield.png",
        ROOT / "img" / "dpgl77-shield-large.png",
        ROOT / "img" / "dpgl77-shield.png",
    ):
        if path.is_file():
            return path
    return None


def _import_pymupdf():
    try:
        import pymupdf as fitz
        return fitz
    except ImportError:
        pass
    try:
        import fitz
        return fitz
    except ImportError:
        raise ImportError(
            "pymupdf is not installed; sending the original PDF. "
            "On this PC run:  pip install pymupdf"
        )


def _watermark_pixmap(fitz, emblem_path, opacity):
    pix = fitz.Pixmap(str(emblem_path))
    if pix.colorspace is not None and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if not pix.alpha:
        pix = fitz.Pixmap(pix, 1)
    n = pix.n
    samples = pix.samples
    alphas = bytes(int(samples[i] * opacity + 0.5) for i in range(n - 1, len(samples), n))
    pix.set_alpha(alphas, premultiply=0)
    return pix


def watermark_pdf(pdf_bytes, user, when=None):
    """Return a new PDF (bytes) with emblem + footer on every page.

    The caller keeps the original file on disk untouched.
    """
    fitz = _import_pymupdf()
    font_path = find_cyrillic_font()
    if font_path is None:
        raise RuntimeError(
            "no Cyrillic TTF found (install Arial on Windows or DejaVu Sans, "
            "or copy DejaVuSans.ttf next to telegram_gate.py)"
        )
    emblem_path = find_emblem()
    if emblem_path is None:
        raise RuntimeError(
            "site emblem not found (expected img/dpgl77-shield-large.png "
            "or img/dpgl77-shield.png in the repo)"
        )
    label = recipient_label(user, when=when)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count == 0:
            raise RuntimeError("PDF has no pages")
        pix = _watermark_pixmap(fitz, emblem_path, WATERMARK_OPACITY)
        fontname = "dpglcyr"
        try:
            align_center = fitz.TEXT_ALIGN_CENTER
        except AttributeError:
            align_center = 1
        for page in doc:
            rect = page.rect
            page_w, page_h = rect.width, rect.height
            max_h = min(page_w, page_h) * 0.62
            max_w = max_h * (pix.width / float(pix.height) if pix.height else 1)
            if max_w > page_w * 0.72:
                max_w = page_w * 0.72
                max_h = max_w * (pix.height / float(pix.width) if pix.width else 1)
            x0 = (page_w - max_w) / 2.0
            y0 = (page_h - max_h) / 2.0 - 8
            page.insert_image(
                fitz.Rect(x0, y0, x0 + max_w, y0 + max_h),
                pixmap=pix,
                keep_proportion=True,
                overlay=True,
            )
            # insert_textbox leftover < 0 means the text did not fit; 8 pt in a
            # 32 pt bar is enough for two short footer lines, including long names.
            bar_h = 32
            page.draw_rect(
                fitz.Rect(0, page_h - bar_h, page_w, page_h),
                color=None,
                fill=(1, 1, 1),
                fill_opacity=0.90,
                width=0,
                overlay=True,
            )
            page.insert_font(fontname=fontname, fontfile=str(font_path))
            footer = f"{SITE_URL}\n{label}"
            page.insert_textbox(
                fitz.Rect(14, page_h - bar_h + 4, page_w - 14, page_h - 3),
                footer,
                fontname=fontname,
                fontfile=str(font_path),
                fontsize=8,
                align=align_center,
                color=(0.12, 0.18, 0.32),
                overlay=True,
            )
        return doc.tobytes(deflate=True)
    finally:
        doc.close()


def send_document(bot_token, chat_id, pdf_path, caption, user=None):
    boundary = "dpgl" + uuid.uuid4().hex
    file_bytes = Path(pdf_path).read_bytes()
    if user is not None:
        try:
            file_bytes = watermark_pdf(file_bytes, user)
        except Exception as exc:
            print(
                f"watermark warning: {exc}. Sending the original PDF. "
                "If pymupdf is missing, install with:  pip install pymupdf"
            )
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


def read_offset():
    if not OFFSET_PATH.exists():
        return 0
    raw = OFFSET_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


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
            "text": (
                "Вы не подписаны на канал @dpgl_news, поэтому PDF не отправлен. "
                "Подпишитесь: https://t.me/dpgl_news "
                "и повторите запрос — снова нажмите «Скачать PDF» "
                f"или отправьте команду /start {payload}."
            ),
        })
        return
    caption = f"<b>{record['title']}</b>\n{record['date_label']}"
    send_document(bot_token, chat["id"], record["pdf"], caption[:1024], user=user)


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
        offset = read_offset()
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
        try:
            import publish_catalog
            publish_catalog.publish_new(bot_token)
        except Exception as exc:
            print(f"catalog error: {exc}")
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def _cli_watermark(argv):
    """python telegram_gate.py --watermark IN.pdf OUT.pdf --username dpgl77 --user-id 123456789"""
    import argparse
    parser = argparse.ArgumentParser(prog="telegram_gate.py --watermark")
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--username", default="")
    parser.add_argument("--user-id", dest="user_id", default="123456789")
    parser.add_argument("--first-name", dest="first_name", default="")
    parser.add_argument("--last-name", dest="last_name", default="")
    args = parser.parse_args(argv)
    user = {
        "id": args.user_id,
        "username": args.username,
        "first_name": args.first_name,
        "last_name": args.last_name,
    }
    out = watermark_pdf(Path(args.src).read_bytes(), user)
    Path(args.dst).write_bytes(out)
    print(f"watermarked {args.dst} ({len(out)} bytes)  {recipient_label(user)}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--watermark":
        try:
            _cli_watermark(sys.argv[2:])
        except Exception as exc:
            print(f"watermark error: {exc}")
            raise SystemExit(1)
    else:
        try:
            main()
        except Exception as exc:
            text = str(exc)
            secret = token()
            if secret:
                text = text.replace(secret, "***")
            print(f"gate error: {text}")
            raise SystemExit(1)

# -*- coding: utf-8 -*-
"""Give a newsletter PDF only to subscribers of @dpgl_news.

The channel post contains https://t.me/dpgl77_bot?start=nl_<token>.
This process reads that /start, checks getChatMember, then sends the file in a private chat.

Before sendDocument the PDF is watermarked in memory (the file in _private
is never modified): a faint DPGL77 shield on every page and a footer with
the site URL plus «специально для @username (ID …) · DD.MM.YYYY».
Needs pymupdf:  pip install pymupdf

Successful subscriber downloads are counted in _private/download_stats.json
(and a PII-free _private/download_counts.json). The channel owner gets a daily
summary at 23:00 local time, or immediately via /stats in a private chat.
The PII-free counts file is force-pushed to the isolated origin/stats branch
via git plumbing (working tree, index and main are never touched).
"""
import os
import hashlib
import html
import json
import subprocess
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
LIMITS_PATH = PRIVATE / "download_limits.json"
STATS_PATH = PRIVATE / "download_stats.json"
COUNTS_PATH = PRIVATE / "download_counts.json"
OWNER_CHAT_PATH = PRIVATE / "owner_chat_id.txt"
PUSHED_SHA_PATH = PRIVATE / "stats_pushed_sha.txt"
REPO = ROOT.parent
STATS_BRANCH = "stats"
STATS_REPO_PATH = "news_letter/download_counts.json"
REPORT_HOUR = 23
REPORT_MINUTE = 0
REPORT_TOP_N = 25
REPORT_CHAR_LIMIT = 3900
CHANNEL = "@dpgl_news"
SUBSCRIBED = {"creator", "administrator", "member"}
UNLIMITED_ROLES = {"creator", "administrator"}
DAILY_LIMIT = 3
DAILY_WINDOW_SEC = 24 * 3600
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


def member_status(bot_token, user_id):
    member = api(bot_token, "getChatMember", {"chat_id": CHANNEL, "user_id": user_id})
    status = member.get("status")
    if status in SUBSCRIBED:
        return status
    if status == "restricted" and bool(member.get("is_member")):
        return "member"
    return None


def subscribed(bot_token, user_id):
    return member_status(bot_token, user_id) is not None


# ------------------------------------------------------------ daily limits
def _load_limits(path=None):
    path = LIMITS_PATH if path is None else path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_limits(data, path=None):
    path = LIMITS_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def check_daily_limit(user_id, file_token, now=None, path=None):
    """Return (allowed, remaining_after, next_available_ts).

    Keyed by immutable numeric Telegram user_id, so unsubscribing/resubscribing
    or changing @username never resets the 24-hour rolling quota.
    Re-downloading a file already fetched in the current 24-hour window does not
    consume an additional slot.
    """
    now = time.time() if now is None else float(now)
    path = LIMITS_PATH if path is None else path
    cutoff = now - DAILY_WINDOW_SEC
    data = _load_limits(path)
    entries = [e for e in data.get(str(user_id), []) if isinstance(e, dict) and e.get("ts", 0) > cutoff]

    by_token = {}
    for e in entries:
        tok = e.get("token")
        ts = float(e.get("ts", 0))
        if tok and (tok not in by_token or ts < by_token[tok]):
            by_token[tok] = ts

    if file_token in by_token:
        remaining = max(0, DAILY_LIMIT - len(by_token))
        return True, remaining, None

    if len(by_token) >= DAILY_LIMIT:
        oldest_ts = min(by_token.values())
        return False, 0, oldest_ts + DAILY_WINDOW_SEC

    remaining_after = max(0, DAILY_LIMIT - (len(by_token) + 1))
    return True, remaining_after, None


def record_download(user_id, file_token, now=None, path=None):
    """Record a successful PDF delivery for user_id and prune expired entries."""
    now = time.time() if now is None else float(now)
    path = LIMITS_PATH if path is None else path
    cutoff = now - DAILY_WINDOW_SEC
    data = _load_limits(path)
    uid = str(user_id)
    entries = [e for e in data.get(uid, []) if isinstance(e, dict) and e.get("ts", 0) > cutoff]
    if not any(e.get("token") == file_token for e in entries):
        entries.append({"token": file_token, "ts": now})
    data[uid] = entries
    for k in list(data.keys()):
        kept = [e for e in data[k] if isinstance(e, dict) and e.get("ts", 0) > cutoff]
        if kept:
            data[k] = kept
        else:
            del data[k]
    _save_limits(data, path)



# ------------------------------------------------------------ download stats
def _atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _empty_day():
    return {
        "delivered": 0,
        "unique_users": [],
        "limit_blocked": 0,
        "not_subscribed": 0,
        "admin_downloads": 0,
    }


def load_stats(path=None):
    path = Path(path) if path is not None else STATS_PATH
    if not path.exists():
        return {"documents": {}, "days": {}, "last_report_date": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"documents": {}, "days": {}, "last_report_date": ""}
        data.setdefault("documents", {})
        data.setdefault("days", {})
        data.setdefault("last_report_date", "")
        return data
    except Exception:
        return {"documents": {}, "days": {}, "last_report_date": ""}


def save_stats(data, path=None):
    path = Path(path) if path is not None else STATS_PATH
    _atomic_write_json(path, data)


def document_key(record):
    """Prefer catalog relpath (the key in catalog.json files); fall back to token."""
    record = record or {}
    relpath = (record.get("relpath") or "").strip()
    if relpath:
        return relpath
    return (record.get("token") or "").strip()


def export_download_counts(stats=None, path=None, now=None):
    """Write a PII-free aggregate map for later use on site cards."""
    stats = load_stats() if stats is None else stats
    path = Path(path) if path is not None else COUNTS_PATH
    now = now or datetime.now()
    counts = {}
    for key, doc in (stats.get("documents") or {}).items():
        if not isinstance(doc, dict):
            continue
        out_key = (doc.get("relpath") or doc.get("token") or key or "").strip()
        if not out_key:
            continue
        counts[out_key] = int(doc.get("total") or 0)
    payload = {
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": counts,
    }
    _atomic_write_json(path, payload)
    return payload


def _day_bucket(stats, day):
    days = stats.setdefault("days", {})
    bucket = days.get(day)
    if not isinstance(bucket, dict):
        bucket = _empty_day()
        days[day] = bucket
    else:
        for key, default in _empty_day().items():
            bucket.setdefault(key, default if not isinstance(default, list) else [])
    return bucket


def _add_unique_user(bucket, user_id):
    if user_id is None or user_id == "":
        return
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        uid = user_id
    users = list(bucket.get("unique_users") or [])
    existing = {str(u) for u in users}
    if str(uid) not in existing:
        users.append(uid)
        bucket["unique_users"] = users


def _bump_document(stats, record, day):
    key = document_key(record)
    if not key:
        return
    docs = stats.setdefault("documents", {})
    doc = docs.get(key)
    if not isinstance(doc, dict):
        doc = {
            "title": "",
            "token": "",
            "relpath": "",
            "total": 0,
            "by_day": {},
        }
    if record.get("title"):
        doc["title"] = record["title"]
    elif not doc.get("title"):
        doc["title"] = key
    if record.get("token"):
        doc["token"] = record["token"]
    if record.get("relpath"):
        doc["relpath"] = record["relpath"]
    elif not doc.get("relpath") and key != doc.get("token"):
        doc["relpath"] = key
    doc["total"] = int(doc.get("total") or 0) + 1
    by_day = doc.setdefault("by_day", {})
    if not isinstance(by_day, dict):
        by_day = {}
        doc["by_day"] = by_day
    by_day[day] = int(by_day.get(day) or 0) + 1
    docs[key] = doc


def record_stat(event, record=None, user_id=None, now=None, stats_path=None, counts_path=None):
    """Record a delivery or a refused request. Admin tests stay out of subscriber totals."""
    now = now or datetime.now()
    day = now.strftime("%Y-%m-%d")
    stats_path = Path(stats_path) if stats_path is not None else STATS_PATH
    counts_path = Path(counts_path) if counts_path is not None else COUNTS_PATH
    stats = load_stats(stats_path)
    bucket = _day_bucket(stats, day)
    if event == "delivered":
        bucket["delivered"] = int(bucket.get("delivered") or 0) + 1
        _add_unique_user(bucket, user_id)
        _bump_document(stats, record or {}, day)
    elif event == "admin_downloads":
        bucket["admin_downloads"] = int(bucket.get("admin_downloads") or 0) + 1
    elif event == "limit_blocked":
        bucket["limit_blocked"] = int(bucket.get("limit_blocked") or 0) + 1
    elif event == "not_subscribed":
        bucket["not_subscribed"] = int(bucket.get("not_subscribed") or 0) + 1
    else:
        raise ValueError(f"unknown stats event: {event}")
    save_stats(stats, stats_path)
    export_download_counts(stats, counts_path, now=now)
    return stats


def _docs_sorted(stats, day=None):
    """Return [(count, title), ...] sorted by count desc, then title."""
    rows = []
    for key, doc in (stats.get("documents") or {}).items():
        if not isinstance(doc, dict):
            continue
        if day is not None:
            count = int((doc.get("by_day") or {}).get(day) or 0)
        else:
            count = int(doc.get("total") or 0)
        if count <= 0:
            continue
        title = doc.get("title") or doc.get("relpath") or key
        rows.append((count, title, key))
    rows.sort(key=lambda r: (-r[0], str(r[1]).casefold(), str(r[2])))
    return [(count, title) for count, title, _key in rows]


def format_report(now=None, stats_path=None):
    """Daily owner report in Russian HTML (no parse_mode entities left unescaped)."""
    now = now or datetime.now()
    day = now.strftime("%Y-%m-%d")
    day_label = now.strftime("%d.%m.%Y")
    stats = load_stats(stats_path)
    raw = (stats.get("days") or {}).get(day) or {}
    delivered = int(raw.get("delivered") or 0)
    unique = len({str(u) for u in (raw.get("unique_users") or [])})
    blocked = int(raw.get("limit_blocked") or 0)
    not_sub = int(raw.get("not_subscribed") or 0)
    admin = int(raw.get("admin_downloads") or 0)

    lines = [
        f"📊 <b>Статистика скачиваний PDF за {day_label}</b>",
        "",
        f"Выдано за день: {delivered}",
        f"Уникальных подписчиков: {unique}",
        f"Отказов по лимиту ({DAILY_LIMIT}/сут): {blocked}",
        f"Не-подписчиков: {not_sub}",
    ]
    if admin:
        lines.append(f"<i>(тестовых скачиваний администратора: {admin})</i>")
    lines.append("")
    lines.append("<b>За сегодня (по убыванию):</b>")
    today_rows = _docs_sorted(stats, day=day)
    if not today_rows:
        lines.append("Скачиваний за сегодня не было.")
    else:
        for count, title in today_rows:
            lines.append(f"{count} — {html.escape(title)}")
    lines.append("")
    lines.append("<b>За всё время (по убыванию):</b>")
    all_rows = _docs_sorted(stats, day=None)
    if not all_rows:
        lines.append("Пока нет скачиваний.")
    else:
        shown = all_rows[:REPORT_TOP_N]
        for count, title in shown:
            lines.append(f"{count} — {html.escape(title)}")
        rest = len(all_rows) - len(shown)
        if rest > 0:
            lines.append(f"…и ещё {rest} документов")
    return "\n".join(lines)


def split_message(text, limit=REPORT_CHAR_LIMIT):
    """Split a report on newlines so each part stays within Telegram's length limit."""
    text = text or ""
    if len(text) <= limit:
        return [text] if text else [""]
    parts = []
    current = []
    current_len = 0
    for line in text.split("\n"):
        # A single oversized line is hard-wrapped.
        while len(line) > limit:
            if current:
                parts.append("\n".join(current))
                current = []
                current_len = 0
            parts.append(line[:limit])
            line = line[limit:]
        add = len(line) + (1 if current else 0)
        if current and current_len + add > limit:
            parts.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += add
    if current:
        parts.append("\n".join(current))
    return parts or [""]


def _coerce_chat_id(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return int(raw)
    except ValueError:
        return raw


def get_owner_chat_id(path=None):
    env = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "").strip()
    if env:
        return _coerce_chat_id(env)
    path = Path(path) if path is not None else OWNER_CHAT_PATH
    if not path.exists():
        return ""
    return _coerce_chat_id(path.read_text(encoding="utf-8"))


def save_owner_chat_id(chat_id, path=None):
    if chat_id is None or str(chat_id).strip() == "":
        return
    path = Path(path) if path is not None else OWNER_CHAT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(str(chat_id).strip() + "\n", encoding="utf-8")
    os.replace(tmp, path)


def send_report(bot_token, chat_id, now=None, stats_path=None, api_func=None):
    api_func = api if api_func is None else api_func
    text = format_report(now=now, stats_path=stats_path)
    for part in split_message(text):
        api_func(bot_token, "sendMessage", {
            "chat_id": chat_id,
            "text": part,
            "parse_mode": "HTML",
        })


def report_due(now=None, stats_path=None, owner_id=None):
    """True when a daily report should be sent: local time >= 23:00, not yet sent today, owner known."""
    now = now or datetime.now()
    if (now.hour, now.minute) < (REPORT_HOUR, REPORT_MINUTE):
        return False
    today = now.strftime("%Y-%m-%d")
    stats = load_stats(stats_path)
    if (stats.get("last_report_date") or "") == today:
        return False
    if not (owner_id if owner_id is not None else get_owner_chat_id()):
        return False
    return True


def maybe_send_daily_report(bot_token, now=None, stats_path=None, api_func=None):
    """Send the daily report once at or after 23:00 local time if the owner chat is known."""
    now = now or datetime.now()
    stats_path = Path(stats_path) if stats_path is not None else STATS_PATH
    chat_id = get_owner_chat_id()
    if not report_due(now=now, stats_path=stats_path, owner_id=chat_id):
        return False
    send_report(bot_token, chat_id, now=now, stats_path=stats_path, api_func=api_func)
    stats = load_stats(stats_path)
    stats["last_report_date"] = now.strftime("%Y-%m-%d")
    save_stats(stats, stats_path)
    maybe_push_stats_branch()
    return True



def _git(repo, args, input_bytes=None, env=None, check=True, timeout=60):
    """Run a git command in repo. Never changes the caller's cwd."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_bytes,
        capture_output=True,
        check=False,
        env=env,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(err or f"git {' '.join(args)}")
    return result


def _git_text(repo, args, input_text=None, env=None, check=True, timeout=60):
    raw = None if input_text is None else input_text.encode("utf-8")
    result = _git(repo, args, input_bytes=raw, env=env, check=check, timeout=timeout)
    return (result.stdout or b"").decode("utf-8", "replace").strip()


def _counts_digest(data):
    return hashlib.sha256(data).hexdigest()


def _last_pushed_digest(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _save_pushed_digest(path, digest):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(digest + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _git_env():
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "dpgl77")
    env.setdefault("GIT_AUTHOR_EMAIL", "dpgl77@users.noreply.github.com")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    return env


def build_stats_commit(repo, data, message="Update PDF download counts"):
    """Create an orphan commit that contains only STATS_REPO_PATH. No checkout."""
    repo = Path(repo)
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    blob = (_git(repo, ["hash-object", "-w", "--stdin"], input_bytes=raw).stdout or b"").decode("utf-8").strip()
    leaf = _git_text(
        repo,
        ["mktree"],
        input_text=f"100644 blob {blob}\tdownload_counts.json\n",
    )
    root = _git_text(
        repo,
        ["mktree"],
        input_text=f"040000 tree {leaf}\tnews_letter\n",
    )
    commit = _git_text(
        repo,
        ["commit-tree", root, "-m", message],
        env=_git_env(),
    )
    return commit


def push_stats_branch(repo=None, counts_path=None, pushed_path=None, remote="origin", force=False):
    """Publish only news_letter/download_counts.json to origin/stats.

    Uses git plumbing (hash-object, mktree, commit-tree) and
    `git push --force origin <sha>:refs/heads/stats`. The working tree,
    index and the current/main branch are never checked out or modified.
    Returns True if a push happened, False if skipped because the file
    is unchanged since the last successful push.
    """
    repo = Path(repo) if repo is not None else REPO
    counts_path = Path(counts_path) if counts_path is not None else COUNTS_PATH
    pushed_path = Path(pushed_path) if pushed_path is not None else PUSHED_SHA_PATH
    if not counts_path.is_file():
        return False
    data = counts_path.read_bytes()
    digest = _counts_digest(data)
    if not force and _last_pushed_digest(pushed_path) == digest:
        return False
    # Confirm this is a git repo without touching its index.
    _git_text(repo, ["rev-parse", "--is-inside-work-tree"])
    commit = build_stats_commit(repo, data)
    _git(
        repo,
        ["push", "--force", remote, f"{commit}:refs/heads/stats"],
        timeout=120,
    )
    # Remember the remote-tracking ref only (not a local stats branch).
    _git(repo, ["update-ref", "refs/remotes/origin/stats" if remote == "origin" else f"refs/remotes/{remote}/stats", commit], check=False)
    _save_pushed_digest(pushed_path, digest)
    print(f"stats branch: pushed {commit[:12]}")
    return True


def maybe_push_stats_branch(repo=None, counts_path=None, pushed_path=None, remote="origin"):
    """Like push_stats_branch, but a network or git error is only logged."""
    try:
        return push_stats_branch(
            repo=repo,
            counts_path=counts_path,
            pushed_path=pushed_path,
            remote=remote,
        )
    except Exception as exc:
        print(f"stats branch warning: {exc}")
        return False

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
    for relpath, record in state.get("files", {}).items():
        if record.get("token") == start_token and Path(record.get("pdf", "")).exists():
            out = dict(record)
            out["relpath"] = relpath
            return out
    return None


def handle(bot_token, message):
    text = message.get("text") or ""
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    if chat.get("type") != "private" or "id" not in user:
        return
    if text.startswith("/stats"):
        status = member_status(bot_token, user["id"])
        if status in UNLIMITED_ROLES:
            save_owner_chat_id(chat["id"])
            send_report(bot_token, chat["id"])
        else:
            api(bot_token, "sendMessage", {
                "chat_id": chat["id"],
                "text": "Команда доступна только администратору.",
            })
        return
    if not text.startswith("/start"):
        return
    payload = text.split(maxsplit=1)[1].strip() if " " in text else ""
    status = member_status(bot_token, user["id"])
    if status in UNLIMITED_ROLES:
        save_owner_chat_id(chat["id"])
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
    if not status:
        api(bot_token, "sendMessage", {
            "chat_id": chat["id"],
            "text": (
                "Вы не подписаны на канал @dpgl_news, поэтому PDF не отправлен. "
                "Подпишитесь: https://t.me/dpgl_news "
                "и повторите запрос — снова нажмите «Скачать PDF» "
                f"или отправьте команду /start {payload}."
            ),
        })
        record_stat("not_subscribed", record=record, user_id=user["id"])
        return
    file_token = record.get("token") or payload[3:]
    is_admin = status in UNLIMITED_ROLES
    remaining = None
    if not is_admin:
        allowed, remaining, next_ts = check_daily_limit(user["id"], file_token)
        if not allowed:
            when_str = datetime.fromtimestamp(next_ts).strftime("%d.%m.%Y в %H:%M")
            api(bot_token, "sendMessage", {
                "chat_id": chat["id"],
                "text": (
                    f"По условиям подписки можно скачать не более {DAILY_LIMIT} PDF-файлов в сутки (за последние 24 часа лимит исчерпан).\n"
                    f"Следующий файл станет доступен {when_str}."
                ),
            })
            record_stat("limit_blocked", record=record, user_id=user["id"])
            return
    caption = f"<b>{record['title']}</b>\n{record['date_label']}"
    if not is_admin:
        caption += f"\n<i>Лимит по подписке: не более {DAILY_LIMIT} PDF в сутки (осталось сегодня: {remaining}).</i>"
    send_document(bot_token, chat["id"], record["pdf"], caption[:1024], user=user)
    if is_admin:
        record_stat("admin_downloads", record=record, user_id=user["id"])
    else:
        record_download(user["id"], file_token)
        record_stat("delivered", record=record, user_id=user["id"])


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
            maybe_send_daily_report(bot_token)
        except Exception as exc:
            print(f"report error: {exc}")
        maybe_push_stats_branch()
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

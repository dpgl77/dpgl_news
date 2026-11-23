# -*- coding: utf-8 -*-
"""Register newsletter PDFs for DPGL_News_Newsletter_Gate.

Does not modify HTML. catalog.json stays in news_letter/_private.
A record with telegram_posted false is waiting for a channel link.
"""
import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "_private"
PDF_ROOT = PRIVATE / "pdf"
STATE_PATH = PRIVATE / "catalog.json"
MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
MONTH_NAME = {value: name for name, value in MONTHS.items()}


def token_for(relative):
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]


def load_state():
    if not STATE_PATH.exists():
        return {"files": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state):
    PRIVATE.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def header_text(raw):
    match = re.search(r"<header>.*?</header>", raw, re.S)
    chunk = match.group(0) if match else raw[:20000]
    chunk = re.sub(r'src="data:image[^"]*"', 'src=""', chunk)
    text = re.sub(r"<[^>]+>", " ", chunk)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(raw, path):
    text = header_text(raw)
    match = re.search(
        r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})",
        text,
        re.I,
    )
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3))
        stamp = datetime(year, month, day)
        return stamp.strftime("%Y-%m-%d"), f"{day} {MONTH_NAME[month]} {year}"
    named = re.search(r"(20\d{2})-(\d{2})-(\d{2})", path.name)
    if named:
        stamp = datetime(int(named.group(1)), int(named.group(2)), int(named.group(3)))
        return stamp.strftime("%Y-%m-%d"), f"{stamp.day} {MONTH_NAME[stamp.month]} {stamp.year}"
    stamp = datetime.fromtimestamp(path.stat().st_mtime)
    return stamp.strftime("%Y-%m-%d"), f"{stamp.day} {MONTH_NAME[stamp.month]} {stamp.year}"


def parse_title(raw, path):
    match = re.search(r"<title>(.*?)</title>", raw, re.S)
    if not match:
        return path.stem
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def message_text(title, date_label, token):
    link = f"https://t.me/dpgl77_bot?start=nl_{token}"
    return (
        "<b>Новости ВПК Турции</b>\n"
        f"<b>{html.escape(title)}</b>\n"
        f"{html.escape(date_label)}\n\n"
        "PDF получает только подписчик канала. Откройте ссылку и нажмите Start: "
        "бот проверит подписку и пришлёт файл.\n"
        f'<a href="{html.escape(link, quote=True)}">Скачать PDF</a>'
    )


def pairs():
    found = []
    if not PDF_ROOT.exists():
        return found
    for pdf in sorted(PDF_ROOT.rglob("*.pdf")):
        relative_pdf = pdf.relative_to(PDF_ROOT).as_posix()
        html_path = ROOT / Path(relative_pdf).with_suffix(".html")
        if not html_path.is_file():
            continue
        relative = html_path.relative_to(ROOT).as_posix()
        found.append((relative, html_path, pdf))
    return found


def register(initial_posted):
    state = load_state()
    files = state.setdefault("files", {})
    pending = []
    for relative, html_path, pdf in pairs():
        raw = html_path.read_text(encoding="utf-8")
        iso, label = parse_date(raw, html_path)
        title = parse_title(raw, html_path)
        record = files.get(relative, {})
        posted = bool(record.get("telegram_posted")) or initial_posted
        # Equipment pages use the same bot link, but they are not reviews
        # and must not be announced in the channel.
        if html_path.parent.name == "VVT":
            posted = True
        record.update({
            "title": title,
            "date": iso,
            "date_label": label,
            "folder": html_path.parent.name,
            "token": token_for(relative),
            "pdf": str(pdf),
            "telegram_posted": posted,
        })
        files[relative] = record
        if not posted:
            pending.append({
                "token": record["token"],
                "relative": relative,
                "text": message_text(title, label, record["token"]),
            })
    save_state(state)
    for item in pending:
        print(json.dumps(item, ensure_ascii=False), flush=True)
    print(f"pending: {len(pending)}", file=sys.stderr, flush=True)
    return pending


def mark_posted(token):
    state = load_state()
    found = False
    for record in state.get("files", {}).values():
        if record.get("token") == token:
            record["telegram_posted"] = True
            found = True
    if not found:
        raise SystemExit(f"token not found: {token}")
    save_state(state)
    print(f"marked: {token}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark-posted", metavar="TOKEN")
    parser.add_argument("--initial-posted", action="store_true")
    args = parser.parse_args()
    if args.mark_posted:
        mark_posted(args.mark_posted)
        return
    register(args.initial_posted)


if __name__ == "__main__":
    main()

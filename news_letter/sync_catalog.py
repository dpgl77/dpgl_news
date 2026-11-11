# -*- coding: utf-8 -*-
"""Rebuild news_letter/index.html from the folder tree and queue new PDFs.

PDFs are written under news_letter/_private/pdf and are not published on the site.
Telegram delivery is a bot deep link: only channel subscribers receive the file.
"""
import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "_private"
PDF_DIR = PRIVATE / "pdf"
STATE_PATH = PRIVATE / "catalog.json"
PENDING_PATH = PRIVATE / "pending_telegram.json"
CHANNEL = "https://t.me/dpgl_news"
BOT_LINK = "https://t.me/dpgl77_bot?start=nl_{token}"

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
EDGE_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
]


def load_state():
    if not STATE_PATH.exists():
        return {"files": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state):
    PRIVATE.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(path):
    return path.read_text(encoding="utf-8")


def header_plain(raw):
    match = re.search(r"<header>.*?</header>", raw, re.S)
    chunk = match.group(0) if match else raw[:20000]
    chunk = re.sub(r'src="data:image[^"]*"', 'src=""', chunk)
    text = re.sub(r"<[^>]+>", " ", chunk)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(raw, path):
    text = header_plain(raw)
    match = re.search(
        r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})",
        text,
        re.I,
    )
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}", f"{day} {match.group(2).lower()} {year}"
    stamp = datetime.fromtimestamp(path.stat().st_mtime)
    label = f"{stamp.day} {MONTH_NAME[stamp.month]} {stamp.year}"
    return stamp.strftime("%Y-%m-%d"), label


def parse_title(raw, path):
    match = re.search(r"<title>(.*?)</title>", raw, re.S)
    if not match:
        return path.stem
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def scan():
    folders = []
    for directory in sorted((p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")), key=lambda p: p.name.lower()):
        items = []
        for path in sorted(directory.glob("*.html"), key=lambda p: p.name.lower()):
            raw = read_text(path)
            iso, label = parse_date(raw, path)
            relative = f"{directory.name}/{path.name}".replace("\\", "/")
            items.append({
                "relative": relative,
                "folder": directory.name,
                "filename": path.name,
                "title": parse_title(raw, path),
                "date": iso,
                "date_label": label,
                "source_mtime": path.stat().st_mtime,
                "source_size": path.stat().st_size,
                "token": hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20],
            })
        items.sort(key=lambda item: (item["date"], item["filename"]), reverse=True)
        folders.append({"name": directory.name, "items": items})
    return folders


def css_value(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_index(folders):
    names = [folder["name"] for folder in folders]
    names_js = json.dumps(names, ensure_ascii=False)
    first = names[0] if names else ""
    active_tabs = ",\n  ".join(
        f'html[data-open="{css_value(name)}"] [data-tab="{css_value(name)}"]' for name in names
    ) or "html[data-open=''] [data-tab='']"
    active_panels = ",\n  ".join(
        f'html[data-open="{css_value(name)}"] [data-panel="{css_value(name)}"]' for name in names
    )
    if first:
        active_panels += f',\n  html:not([data-open]) [data-panel="{css_value(first)}"]'
    else:
        active_panels = "html[data-open=''] [data-panel='']"

    buttons = "\n    ".join(
        f'<button type="button" id="tab-{html.escape(name, quote=True)}" data-tab="{html.escape(name, quote=True)}" role="tab" aria-controls="panel-{html.escape(name, quote=True)}">{html.escape(name)}</button>'
        for name in names
    )
    sections = []
    for folder in folders:
        cards = []
        for item in folder["items"]:
            cards.append(
                "    <a class=\"review\" href=\"{href}\">\n"
                "      <time datetime=\"{iso}\">{label}</time>\n"
                "      <span>\n"
                "        <span class=\"name\">{title}</span>\n"
                "        <span class=\"file\">{filename}</span>\n"
                "      </span>\n"
                "    </a>".format(
                    href=html.escape(item["relative"], quote=True),
                    iso=html.escape(item["date"], quote=True),
                    label=html.escape(item["date_label"]),
                    title=html.escape(item["title"]),
                    filename=html.escape(item["filename"]),
                )
            )
        body = "\n".join(cards) if cards else '    <p class="file">В этой папке пока нет обзоров.</p>'
        sections.append(
            f'<section id="panel-{html.escape(folder["name"], quote=True)}" data-panel="{html.escape(folder["name"], quote=True)}" role="tabpanel" aria-labelledby="tab-{html.escape(folder["name"], quote=True)}">\n{body}\n  </section>'
        )
    empty = "" if names else '<p class="file">В каталоге пока нет обзоров.</p>\n'
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Бюллетени и обзоры — DPGL NEWS</title>
<script>
(function () {{
  var ids = {names_js};
  var h = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  if (ids.indexOf(h) === -1) h = ids[0] || "";
  if (h) document.documentElement.setAttribute("data-open", h);
}})();
</script>
<style>
  :root {{
    --navy: #0b1f3a;
    --burgundy: #8b0000;
    --ink: #1d2433;
    --muted: #5c677a;
    --paper: #eef1f5;
    --line: #d5dbe3;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", Roboto, Arial, sans-serif;
    background: var(--paper);
    color: var(--ink);
    line-height: 1.5;
  }}
  a {{ color: var(--navy); }}
  .top {{
    background: linear-gradient(135deg, var(--navy), var(--burgundy));
    color: #fff;
    padding: 28px 20px 26px;
  }}
  .top-inner, .wrap {{ max-width: 920px; margin: 0 auto; }}
  .brand {{
    margin: 0 0 8px;
    letter-spacing: .14em;
    font-size: 12px;
    font-weight: 700;
  }}
  h1 {{ margin: 0 0 10px; font-size: 32px; font-weight: 700; line-height: 1.15; }}
  .lead {{ margin: 0; max-width: 46rem; color: rgba(255,255,255,.92); }}
  .lead a {{ color: #fff; font-weight: 700; }}
  .tg {{
    display: inline-block;
    margin-top: 16px;
    background: #fff;
    color: var(--navy);
    text-decoration: none;
    font-weight: 700;
    border-radius: 999px;
    padding: 8px 14px;
  }}
  .tg:hover {{ background: #f3f6fb; }}
  .wrap {{ padding: 18px 20px 48px; }}
  .tabs {{
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding-bottom: 4px;
    margin-bottom: 16px;
  }}
  .tabs button {{
    appearance: none;
    border: 1px solid var(--line);
    background: #fff;
    color: var(--navy);
    border-radius: 999px;
    padding: 8px 14px;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
  }}
  .tabs button:hover {{ border-color: var(--navy); }}
  {active_tabs} {{
    background: var(--navy);
    border-color: var(--navy);
    color: #fff;
  }}
  [data-panel] {{ display: none; }}
  {active_panels} {{ display: block; }}
  .review {{
    display: grid;
    grid-template-columns: 11.5rem minmax(0, 1fr);
    gap: 6px 22px;
    align-items: baseline;
    background: #fff;
    color: inherit;
    text-decoration: none;
    border-radius: 12px;
    padding: 16px 18px;
    margin: 0 0 12px;
    box-shadow: 0 2px 10px rgba(0,0,0,.06);
    border-left: 4px solid transparent;
  }}
  .review:hover {{ border-left-color: var(--burgundy); }}
  .review time {{
    color: var(--burgundy);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }}
  .name {{ display: block; font-size: 18px; font-weight: 700; color: var(--navy); }}
  .file {{ display: block; margin-top: 3px; color: var(--muted); font-size: 13px; }}
  .foot {{
    margin-top: 22px;
    color: var(--muted);
    font-size: 14px;
  }}
  .foot a {{ font-weight: 700; }}
  @media (max-width: 640px) {{
    h1 {{ font-size: 26px; }}
    .review {{ grid-template-columns: 1fr; gap: 4px; }}
  }}
</style>
<noscript>
<style>
  [data-panel] {{ display: block !important; margin-top: 22px; }}
  .tabs {{ display: none; }}
</style>
</noscript>
</head>
<body>
<header class="top">
  <div class="top-inner">
    <p class="brand">DPGL NEWS</p>
    <h1>Бюллетени и обзоры</h1>
    <p class="lead">Текст обзора открывается по ссылке. Копирование и печать отключены: PDF получает подписчик канала <a href="{CHANNEL}">{CHANNEL}</a>.</p>
    <a class="tg" href="{CHANNEL}">Открыть канал DPGL_News</a>
  </div>
</header>
<div class="wrap">
  <div class="tabs" role="tablist" aria-label="Папки обзоров">
    {buttons}
  </div>

  {empty}{chr(10).join(sections)}

  <p class="foot">PDF-файлы этих обзоров получает подписчик канала <a href="{CHANNEL}">{CHANNEL}</a>.</p>
</div>
<script>
(function () {{
  var root = document.documentElement;
  var tabs = document.querySelectorAll("[data-tab]");
  var order = {names_js};
  function sync(id, push) {{
    root.setAttribute("data-open", id);
    tabs.forEach(function (tab) {{
      var on = tab.getAttribute("data-tab") === id;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
    }});
    if (push) history.replaceState(null, "", "#" + encodeURIComponent(id));
  }}
  if (order.length) sync(root.getAttribute("data-open") || order[0], false);
  tabs.forEach(function (tab) {{
    tab.addEventListener("click", function () {{
      sync(tab.getAttribute("data-tab"), true);
    }});
  }});
  var tablist = document.querySelector("[role=tablist]");
  if (tablist) tablist.addEventListener("keydown", function (e) {{
    var current = root.getAttribute("data-open");
    var i = order.indexOf(current);
    if (e.key === "ArrowRight") i = (i + 1) % order.length;
    else if (e.key === "ArrowLeft") i = (i - 1 + order.length) % order.length;
    else return;
    e.preventDefault();
    sync(order[i], true);
    document.getElementById("tab-" + order[i]).focus();
  }});
}})();
</script>
</body>
</html>
"""


def printable_html(raw):
    raw = re.sub(
        r'<style id="dpgl-guard-style">.*?</style>\s*<script>.*?</script>',
        "",
        raw,
        count=1,
        flags=re.S,
    )
    raw = re.sub(
        r'<div id="dpgl-guard">.*?</div>\s*<div id="dpgl-print-only">.*?</div>\s*',
        "",
        raw,
        count=1,
        flags=re.S,
    )
    extra = "<style>@media print { * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; } }</style>"
    return raw.replace("</head>", extra + "</head>", 1)


def find_browser():
    for path in EDGE_CANDIDATES:
        if path.exists():
            return path
    return None


def build_pdf(source, destination):
    browser = find_browser()
    if browser is None:
        raise RuntimeError("Edge or Chrome was not found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="dpgl-pdf-"))
    temp_html = destination.with_suffix(".print.html")
    temp_html.write_text(printable_html(read_text(source)), encoding="utf-8")
    if destination.exists():
        destination.unlink()
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        f"--user-data-dir={profile}",
        "--no-pdf-header-footer",
        f"--print-to-pdf={destination}",
        temp_html.resolve().as_uri(),
    ]
    try:
        subprocess.run(command, check=False, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        if temp_html.exists():
            temp_html.unlink()
    if not destination.exists() or destination.stat().st_size < 1000:
        raise RuntimeError(f"PDF was not created for {source.name}")


def message_text(item):
    link = BOT_LINK.format(token=item["token"])
    return (
        "<b>Новости ВПК Турции</b>\n"
        f"<b>{html.escape(item['title'])}</b>\n"
        f"{html.escape(item['date_label'])}\n\n"
        "PDF получает только подписчик канала. Откройте ссылку и нажмите Start: "
        "бот проверит подписку и пришлёт файл.\n"
        f'<a href="{html.escape(link, quote=True)}">Скачать PDF</a>'
    )


def write_pending(entries):
    PRIVATE.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync():
    folders = scan()
    generated = render_index(folders).replace("\r\n", "\n")
    index_path = ROOT / "index.html"
    current = index_path.read_text(encoding="utf-8").replace("\r\n", "\n") if index_path.exists() else ""
    index_status = "unchanged"
    if current != generated:
        index_path.write_text(generated, encoding="utf-8")
        index_status = "rewritten"

    state = load_state()
    files = state.setdefault("files", {})
    built = 0
    for folder in folders:
        for item in folder["items"]:
            record = files.get(item["relative"], {})
            source = ROOT / item["relative"]
            pdf_path = PDF_DIR / (item["token"] + ".pdf")
            changed = (
                record.get("source_mtime") != item["source_mtime"]
                or record.get("source_size") != item["source_size"]
                or not pdf_path.exists()
            )
            if changed:
                build_pdf(source, pdf_path)
                built += 1
            record.update({
                "title": item["title"],
                "date": item["date"],
                "date_label": item["date_label"],
                "folder": item["folder"],
                "token": item["token"],
                "pdf": str(pdf_path),
                "source_mtime": item["source_mtime"],
                "source_size": item["source_size"],
                "telegram_posted": bool(record.get("telegram_posted")),
            })
            files[item["relative"]] = record
    save_state(state)

    pending = []
    for record in files.values():
        if record.get("telegram_posted"):
            continue
        if not Path(record.get("pdf", "")).exists():
            continue
        pending.append({
            "token": record["token"],
            "relative": next(key for key, value in files.items() if value is record),
            "title": record["title"],
            "date_label": record["date_label"],
            "pdf": record["pdf"],
            "text": message_text(record),
        })
    pending.sort(key=lambda item: item["relative"])
    write_pending(pending)
    print(f"index: {index_status}")
    print(f"pdf_built: {built}")
    print(f"pending: {len(pending)}")
    print(f"pending_file: {PENDING_PATH}")


def mark_posted(token, message_id):
    state = load_state()
    found = False
    for record in state.get("files", {}).values():
        if record.get("token") == token:
            record["telegram_posted"] = True
            record["message_id"] = message_id
            record["posted_at"] = datetime.now().isoformat(timespec="seconds")
            found = True
            break
    if not found:
        raise SystemExit(f"unknown token: {token}")
    save_state(state)
    pending = []
    if PENDING_PATH.exists():
        pending = [item for item in json.loads(PENDING_PATH.read_text(encoding="utf-8")) if item.get("token") != token]
    write_pending(pending)
    print(f"marked: {token} message_id={message_id}")
    print(f"pending: {len(pending)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark-posted", nargs=2, metavar=("TOKEN", "MESSAGE_ID"))
    args = parser.parse_args()
    if args.mark_posted:
        mark_posted(args.mark_posted[0], str(args.mark_posted[1]))
        return
    sync()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

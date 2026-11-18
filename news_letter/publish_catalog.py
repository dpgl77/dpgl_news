# -*- coding: utf-8 -*-
"""Update the newsletter catalog when new HTML reviews appear.

Used by DPGL_News_Newsletter_Gate. Mirrors prompt.txt algorithm steps 4-6
and the git steps after them. Does not build the daily briefing or the
source ranking. PDF conversion never writes the source HTML.
"""
import html
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import register_pdf

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
PDF_ROOT = ROOT / "_private" / "pdf"
LOCK_PATH = ROOT / "_private" / "gate.lock"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CHANNEL = "@dpgl_news"


def review_files():
    return [
        path for path in sorted(ROOT.rglob("*.html"))
        if path.name != "index.html" and "_private" not in path.parts
    ]


def download_paragraph(token):
    link = f"https://t.me/dpgl77_bot?start=nl_{token}"
    return (
        '<p id="dpgl-pdf-link" style="max-width:900px;margin:24px auto;padding:0 16px;'
        'font-family:Segoe UI,Roboto,Arial,sans-serif;font-size:16px;line-height:1.4">'
        f'<a href="{html.escape(link, quote=True)}">Скачать PDF</a></p>'
    )


def ensure_download_links():
    changed = []
    for path in review_files():
        raw = path.read_text(encoding="utf-8")
        if 'id="dpgl-pdf-link"' in raw:
            continue
        relative = path.relative_to(ROOT).as_posix()
        paragraph = download_paragraph(register_pdf.token_for(relative))
        if "</body>" in raw:
            raw = raw.replace("</body>", paragraph + "</body>", 1)
        else:
            raw += paragraph
        path.write_text(raw, encoding="utf-8")
        changed.append(relative)
    return changed


def card(href, iso, label, title):
    return (
        f'    <a class="review" href="{html.escape(href, quote=True)}">\n'
        f'      <time datetime="{iso}">{html.escape(label)}</time>\n'
        f'      <span class="name">{html.escape(title)}</span>\n'
        "    </a>\n"
    )


def ensure_index():
    index_path = ROOT / "index.html"
    text = index_path.read_text(encoding="utf-8")
    present = set(re.findall(r'href="([^"]+\.html)"', text))
    added = []
    for path in review_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in present or f"{path.parent.name}/{path.name}" in present:
            continue
        raw = path.read_text(encoding="utf-8")
        iso, label = register_pdf.parse_date(raw, path)
        title = register_pdf.parse_title(raw, path)
        folder = path.parent.name
        marker = f'data-panel="{folder}"'
        if marker not in text:
            print(f"index: no tab for {folder}, skipped {relative}")
            continue
        block = card(relative, iso, label, title)
        section = re.search(
            rf'(<section id="panel-{re.escape(folder)}"[^>]*>)(.*?)(</section>)',
            text,
            re.S,
        )
        if not section:
            print(f"index: section missing for {folder}")
            continue
        body = section.group(2)
        cards = list(re.finditer(r'<a class="review"[\s\S]*?</a>\s*', body))
        insert_at = len(body)
        for found in cards:
            stamp = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', found.group(0))
            if stamp and stamp.group(1) < iso:
                insert_at = found.start()
                break
            insert_at = found.end()
        body = body[:insert_at] + block + body[insert_at:]
        text = text[:section.start(2)] + body + text[section.end(2):]
        present.add(relative)
        added.append(relative)
    if added:
        index_path.write_text(text, encoding="utf-8")
    return added


def printable_html(raw):
    raw = re.sub(
        r'<style id="dpgl-guard-style">.*?</style>\s*(?:<script(?:\s[^>]*)?>.*?</script>\s*)?',
        "",
        raw,
        count=1,
        flags=re.S,
    )
    raw = re.sub(r'<style id="protect-css">.*?</style>\s*', "", raw, count=1, flags=re.S)
    raw = re.sub(r'<script id="protect-js">.*?</script>\s*', "", raw, count=1, flags=re.S)
    raw = re.sub(r'<div id="dpgl-guard">.*?</div>\s*', "", raw, count=1, flags=re.S)
    raw = re.sub(r'<div id="dpgl-print-only">.*?</div>\s*', "", raw, count=1, flags=re.S)
    raw = raw.replace(
        "@media print{html,body{display:none!important;visibility:hidden!important}}",
        "",
    )
    extra = (
        "<style>@media print { html, body { display: block !important; visibility: visible !important; } "
        "* { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; } }</style>"
    )
    return raw.replace("</head>", extra + "</head>", 1)


def build_missing_pdfs():
    browser = EDGE if EDGE.exists() else CHROME
    built = []
    if not browser.exists():
        print("pdf: browser not found")
        return built
    for path in review_files():
        relative = path.relative_to(ROOT).with_suffix(".pdf")
        destination = PDF_ROOT / relative
        if destination.exists() and destination.stat().st_size > 1000:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        profile = Path(tempfile.mkdtemp(prefix="dpgl-pdf-"))
        temp_html = destination.with_suffix(".print.html")
        temp_html.write_text(printable_html(path.read_text(encoding="utf-8")), encoding="utf-8")
        if destination.exists():
            destination.unlink()
        command = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            "--no-pdf-header-footer",
            "--virtual-time-budget=30000",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={destination}",
            temp_html.resolve().as_uri(),
        ]
        try:
            if LOCK_PATH.exists():
                LOCK_PATH.touch()
            subprocess.run(command, check=False, timeout=240, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            if temp_html.exists():
                temp_html.unlink()
            shutil.rmtree(profile, ignore_errors=True)
        if destination.exists() and destination.stat().st_size > 1000:
            built.append(relative.as_posix())
            print(f"pdf: {relative.as_posix()}")
        else:
            print(f"pdf failed: {relative.as_posix()}")
    return built


def send_channel(bot_token, text):
    payload = urllib.parse.urlencode({
        "chat_id": CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
            import json
            result = json.loads(body.decode("utf-8"))
            if result.get("ok"):
                return True
            print(f"telegram: {result.get('description')}")
            return False
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code == 429 and attempt < 3:
                wait = 5
                match = re.search(r'"retry_after":\s*(\d+)', detail)
                if match:
                    wait = int(match.group(1)) + 1
                time.sleep(wait)
                continue
            print(f"telegram error: {exc.code}")
            return False
    return False


def announce_new(bot_token):
    pending = register_pdf.register(False) or []
    posted = []
    for item in pending:
        if send_channel(bot_token, item["text"]):
            register_pdf.mark_posted(item["token"])
            posted.append(item["relative"])
    return posted


def git_publish():
    html_files = [
        str(path.relative_to(REPO)).replace("\\", "/")
        for path in review_files()
    ]
    html_files.append("news_letter/index.html")
    subprocess.run(["git", "add", "--", *html_files], cwd=REPO, check=False)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    if not staged:
        print("git: nothing to commit")
        return False
    message = f"News articles {date.today().isoformat()}"
    committed = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=REPO,
        check=False,
    )
    if committed.returncode != 0:
        print("git: commit failed")
        return False
    pushed = subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=False)
    print(f"git: push {pushed.returncode}")
    return pushed.returncode == 0


def publish_new(bot_token):
    linked = ensure_download_links()
    indexed = ensure_index()
    built = build_missing_pdfs()
    posted = announce_new(bot_token) if bot_token else []
    if linked or indexed or built or posted:
        git_publish()
    print(
        f"catalog: links {len(linked)}, index {len(indexed)}, "
        f"pdf {len(built)}, posted {len(posted)}"
    )

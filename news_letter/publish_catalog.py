# -*- coding: utf-8 -*-
"""Update the newsletter catalog when new HTML reviews appear.

Used by DPGL_News_Newsletter_Gate. Mirrors prompt.txt algorithm steps 4-6
and the git steps after them. Does not build the daily briefing or the
source ranking. PDF conversion never writes the source HTML.
"""
import html
import json
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
SITE = "https://dpgl77.github.io/dpgl_news"
SKIP_DIRS = {"_private", "__pycache__"}
# VVT is the equipment catalog, opened from the site root. It stays inside
# news_letter so the published URLs stay valid, and it is not a news tab.
CATALOG_SKIP = {"VVT"}


def content_folders():
    names = [
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and path.name not in SKIP_DIRS and not path.name.startswith(".")
    ]
    names.sort(key=str.casefold)
    return names


def catalog_folders():
    names = [name for name in content_folders() if name not in CATALOG_SKIP]
    if "Articles" in names:
        names.remove("Articles")
        names.insert(0, "Articles")
    return names


def html_files(folders):
    files = []
    for name in folders:
        files.extend(sorted((ROOT / name).glob("*.html")))
    return files


def review_files():
    return html_files(catalog_folders())


def equipment_files():
    """Equipment reference pages. They are not news tabs. index.html is not a PDF."""
    files = []
    for name in sorted(CATALOG_SKIP):
        folder = ROOT / name
        if not folder.is_dir():
            continue
        files.extend(
            path for path in sorted(folder.glob("*.html"))
            if path.name.lower() != "index.html"
        )
    return files


def pdf_source_files():
    return review_files() + equipment_files()


def download_paragraph(token):
    link = f"https://t.me/dpgl77_bot?start=nl_{token}"
    return (
        '<p id="dpgl-pdf-link" style="max-width:900px;margin:24px auto;padding:0 16px;'
        'font-family:Segoe UI,Roboto,Arial,sans-serif;font-size:16px;line-height:1.4">'
        f'<a href="{html.escape(link, quote=True)}">Скачать PDF</a></p>'
    )


def ensure_download_links():
    changed = []
    for path in pdf_source_files():
        with open(path, encoding="utf-8", newline="") as handle:
            raw = handle.read()
        if 'id="dpgl-pdf-link"' in raw:
            continue
        relative = path.relative_to(ROOT).as_posix()
        paragraph = download_paragraph(register_pdf.token_for(relative))
        if "</body>" in raw:
            raw = raw.replace("</body>", paragraph + "</body>", 1)
        else:
            raw += paragraph
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(raw)
        changed.append(relative)
    return changed


HEADER_STYLE_OLD = """
/* site-wide header, same as news_letter/index.html */
header.top{background:linear-gradient(135deg,#0b1f3a,#8b0000);color:#fff;padding:16px 20px 14px}
header.top .top-inner{max-width:42rem;margin:0 auto}
header.top .brand{margin:0 0 2px;letter-spacing:.14em;font-size:11px;font-weight:700}
header.top h1{margin:0;font-size:26px;font-weight:700;line-height:1.25}
header.top .title-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
header.top .title-row h1{flex:1 1 auto;min-width:0}
header.top a.back{flex:0 0 auto;background:#fff;color:#0b1f3a;border-radius:6px;padding:6px 14px;font-size:15px;font-weight:700;text-decoration:none;line-height:1.2}
header.top a.back:hover{background:#eef1f5}
header.top a.back:focus-visible{outline:2px solid #fff;outline-offset:2px}
header.top .meta{margin-top:6px}
header.top .hero{margin:14px -20px -14px}
header.top .hero img{width:100%;max-height:460px;object-fit:cover;display:block}
#dpgl-guard:empty{display:none}
body.is-index header.top .top-inner{max-width:72rem}
@media (max-width:640px){header.top h1{font-size:20px}}
@media print{header.top a.back{display:none}}
"""

HEADER_STYLE_NEW = """
/* site-wide header, same as news_letter/index.html. The title bar stays put. */
header.top{position:sticky;top:0;z-index:40;background:linear-gradient(135deg,#0b1f3a,#8b0000);color:#fff;padding:16px 20px 14px}
header.top .top-inner{max-width:42rem;margin:0 auto}
header.top .brand{margin:0 0 2px;letter-spacing:.14em;font-size:11px;font-weight:700}
header.top h1{margin:0;font-size:26px;font-weight:700;line-height:1.25}
header.top .title-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
header.top .title-row h1{flex:1 1 auto;min-width:0}
header.top a.back{flex:0 0 auto;background:#fff;color:#0b1f3a;border-radius:6px;padding:6px 14px;font-size:15px;font-weight:700;text-decoration:none;line-height:1.2}
header.top a.back:hover{background:#eef1f5}
header.top a.back:focus-visible{outline:2px solid #fff;outline-offset:2px}
header.top .meta{margin-top:6px}
.hero{margin:0}
.hero img{width:100%;max-height:460px;object-fit:cover;display:block}
#dpgl-guard:empty{display:none}
body.is-index header.top .top-inner{max-width:72rem}
@media (max-width:640px){header.top h1{font-size:20px}}
@media print{header.top{position:static}header.top a.back{display:none}}
"""


def _with_newlines(text, newline):
    return text.replace("\n", newline)


def move_cover_out_of_header(raw):
    """Keep the cover in the scrolling page. A sticky header must stay a short title bar."""
    match = re.search(r'<header class="top">(.*?)</header>', raw, re.S)
    if not match or 'class="hero"' not in match.group(1):
        return raw
    hero_match = re.search(r'<div class="hero">.*?</div>', match.group(1), re.S)
    if not hero_match:
        return raw
    inner = match.group(1)[:hero_match.start()] + match.group(1)[hero_match.end():]
    return (
        raw[:match.start()]
        + '<header class="top">'
        + inner
        + "</header>"
        + hero_match.group(0)
        + raw[match.end():]
    )


def ensure_fixed_headers():
    """Pin the title bar with «Назад» on review pages. VVT is left scrolling."""
    changed = []
    for path in review_files():
        with open(path, encoding="utf-8", newline="") as handle:
            raw = handle.read()
        if 'class="back"' not in raw or 'class="top"' not in raw:
            continue
        original = raw
        newline = "\r\n" if "\r\n" in raw else "\n"
        old_style = "<style id=\"site-header-v1\">" + _with_newlines(HEADER_STYLE_OLD, newline) + "</style>"
        new_style = "<style id=\"site-header-v1\">" + _with_newlines(HEADER_STYLE_NEW, newline) + "</style>"
        if old_style in raw:
            raw = raw.replace(old_style, new_style, 1)
        elif 'id="site-header-v1"' not in raw:
            raw = raw.replace("</head>", new_style + "</head>", 1)
        elif "position:sticky" not in raw:
            raw = raw.replace(
                "header.top{",
                "header.top{position:sticky;top:0;z-index:40;",
                1,
            )
            raw = raw.replace(
                "@media print{header.top a.back{display:none}}",
                "@media print{header.top{position:static}header.top a.back{display:none}}",
                1,
            )
            raw = raw.replace("header.top .hero{", ".hero{")
            raw = raw.replace("header.top .hero img{", ".hero img{")
        raw = move_cover_out_of_header(raw)
        if raw == original:
            continue
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(raw)
        changed.append(path.relative_to(ROOT).as_posix())
    return changed


def card(href, iso, label, title):
    return (
        f'    <a class="review" href="{html.escape(href, quote=True)}">\n'
        f'      <time datetime="{iso}">{html.escape(label)}</time>\n'
        f'      <span class="name">{html.escape(title)}</span>\n'
        "    </a>\n"
    )


def catalog_tabs(text):
    match = re.search(
        r'<script type="application/json" id="catalog-tabs">(.*?)</script>',
        text,
        re.S,
    )
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def catalog_css(folders):
    if not folders:
        return "  [data-panel] { display: none; }\n"
    tab_rules = ",\n".join(
        f'  html[data-open="{name}"] [data-tab="{name}"]' for name in folders
    )
    panel_rules = ",\n".join(
        f'  html[data-open="{name}"] [data-panel="{name}"]' for name in folders
    )
    first = folders[0]
    return (
        "  [data-panel] { display: none; }\n"
        f"{tab_rules} {{\n"
        "    background: var(--navy);\n"
        "    border-color: var(--navy);\n"
        "    color: #fff;\n"
        "  }\n"
        f"{panel_rules},\n"
        f'  html:not([data-open]) [data-panel="{first}"] {{ display: block; }}\n'
    )


def render_index(text, folders, groups):
    payload = json.dumps(folders, ensure_ascii=False)
    text, count = re.subn(
        r"/\* catalog-css \*/.*?/\* /catalog-css \*/",
        "/* catalog-css */\n" + catalog_css(folders) + "  /* /catalog-css */",
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        return None
    text, count = re.subn(
        r'(<script type="application/json" id="catalog-tabs">).*?(</script>)',
        lambda match: match.group(1) + payload + match.group(2),
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        return None
    button_lines = []
    section_blocks = []
    for name in folders:
        esc = html.escape(name, quote=True)
        button_lines.append(
            f'    <button type="button" id="tab-{esc}" data-tab="{esc}" role="tab" '
            f'aria-controls="panel-{esc}">{html.escape(name)}</button>'
        )
        cards = [
            card(relative, iso, label, title).rstrip("\n")
            for iso, relative, label, title in groups[name]
        ]
        body = "\n" + "\n".join(cards) + "\n  " if cards else ""
        section_blocks.append(
            f'  <section id="panel-{esc}" data-panel="{esc}" role="tabpanel" '
            f'aria-labelledby="tab-{esc}">{body}</section>'
        )
    buttons = "\n".join(button_lines)
    sections = "\n".join(section_blocks)
    text, count = re.subn(
        r'(<div class="tabs" role="tablist" aria-label="Папки обзоров">).*?(</div>)',
        lambda match: match.group(1) + "\n" + buttons + "\n  " + match.group(2),
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        return None
    text, count = re.subn(
        r'(</div>)\s*(?:<section id="panel-[\s\S]*?</section>\s*)*(?=\s*<p class="foot">)',
        lambda match: match.group(1) + "\n\n" + sections + "\n\n  ",
        text,
        count=1,
    )
    if count != 1:
        return None
    return text


def ensure_index():
    index_path = ROOT / "index.html"
    data = index_path.read_bytes()
    crlf = b"\r\n" in data
    text = data.decode("utf-8").replace("\r\n", "\n")
    folders = catalog_folders()
    files = review_files()
    current = {path.relative_to(ROOT).as_posix() for path in files}
    hrefs = {
        href
        for href in re.findall(r'href="((?:[^"]+/)+[^"]+\.html)"', text)
        if not href.startswith((".", "/"))
    }
    tabs = catalog_tabs(text)
    newest = max((path.stat().st_mtime for path in files), default=0)
    if tabs == folders and hrefs == current and newest <= index_path.stat().st_mtime + 1:
        return []
    groups = {name: [] for name in folders}
    for path in files:
        raw = path.read_text(encoding="utf-8")
        iso, label = register_pdf.parse_date(raw, path)
        title = register_pdf.parse_title(raw, path)
        relative = path.relative_to(ROOT).as_posix()
        groups[path.parent.name].append((iso, relative, label, title))
    for name in groups:
        groups[name].sort(key=lambda item: (item[0], item[1]), reverse=True)
    updated = render_index(text, folders, groups)
    if updated is None:
        print("index: template missing, not written")
        return []
    if (
        len(updated) < 2000
        or "<!DOCTYPE html>" not in updated
        or '<p class="foot"' not in updated
        or "catalog-tabs" not in updated
    ):
        print("index: refused to write incomplete page")
        return []
    if updated == text:
        return []
    out = updated.replace("\n", "\r\n") if crlf else updated
    index_path.write_bytes(out.encode("utf-8"))
    added = sorted(current - hrefs)
    removed = sorted(hrefs - current)
    print(f"index: folders {len(folders)}, added {len(added)}, removed {len(removed)}")
    return added or ["index.html"]


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
    for path in pdf_source_files():
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


def page_url(path):
    rel = path.relative_to(REPO).as_posix()
    if rel == "index.html":
        return SITE + "/"
    if rel.endswith("/index.html"):
        rel = rel[: -len("index.html")]
    return SITE + "/" + urllib.parse.quote(rel, safe="/")


def lastmod(path):
    rel = path.relative_to(REPO).as_posix()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", rel],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not status:
        committed = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", rel],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if committed:
            return committed
    return date.fromtimestamp(path.stat().st_mtime).isoformat()


def public_pages():
    hubs = [
        REPO / "index.html",
        ROOT / "index.html",
        REPO / "sources_ranking.html",
    ]
    pages = [path for path in hubs if path.is_file()]
    pages.extend(html_files(content_folders()))
    return pages


def write_sitemap():
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in public_pages():
        loc = html.escape(page_url(path), quote=False)
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{lastmod(path)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    text = "\n".join(lines) + "\n"
    target = REPO / "sitemap.xml"
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return False
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"sitemap: {len(public_pages())} urls")
    return True


def commit_message(names):
    today = date.today().isoformat()
    paths = [name.replace("\\", "/") for name in names]
    news = [path for path in paths if path.startswith("news_letter/")]
    ranking = [path for path in paths if path == "sources_ranking.html"]
    other = [path for path in paths if path not in news and path not in ranking]
    if paths and not other and not news:
        return f"Update source ranking {today}"
    if paths and not other and not ranking:
        return f"News articles {today}"
    if paths and not other and news and ranking:
        return f"News articles and source ranking {today}"
    return f"Update dpgl_news {today}"


def git_publish():
    subprocess.run(["git", "add", "-A"], cwd=REPO, check=False)
    subprocess.run(
        ["git", "reset", "-q", "--", "news_letter/_private", "news_letter/__pycache__"],
        cwd=REPO,
        check=False,
    )
    staged_raw = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    staged = []
    for name in staged_raw.split("\0"):
        if not name:
            continue
        parts = name.replace("\\", "/").split("/")
        if "_private" in parts or "__pycache__" in parts or name.endswith(".pyc"):
            subprocess.run(["git", "reset", "-q", "--", name], cwd=REPO, check=False)
            continue
        staged.append(name)
    if not staged:
        print("git: nothing to commit")
        return False
    message = commit_message(staged)
    committed = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=REPO,
        check=False,
    )
    if committed.returncode != 0:
        print("git: commit failed")
        return False
    pushed = subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=False)
    if pushed.returncode != 0:
        print("git: push failed, rebase once")
        pulled = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=REPO,
            check=False,
        )
        if pulled.returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=REPO, check=False)
            print("git: rebase failed")
            return False
        pushed = subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=False)
    print(f"git: push {pushed.returncode} {message}")
    return pushed.returncode == 0


def publish_new(bot_token):
    linked = ensure_download_links()
    fixed = ensure_fixed_headers()
    indexed = ensure_index()
    built = build_missing_pdfs()
    posted = announce_new(bot_token) if bot_token else []
    write_sitemap()
    git_publish()
    print(
        f"catalog: links {len(linked)}, headers {len(fixed)}, index {len(indexed)}, "
        f"pdf {len(built)}, posted {len(posted)}"
    )


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-index", action="store_true")
    args = parser.parse_args()
    if not args.sync_index:
        raise SystemExit("usage: publish_catalog.py --sync-index")
    changed = ensure_index()
    print("index: updated" if changed else "index: unchanged")


if __name__ == "__main__":
    main()

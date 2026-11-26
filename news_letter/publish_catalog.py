# -*- coding: utf-8 -*-
"""Build newsletter PDFs and announce new reviews (DPGL_News_Newsletter_Gate).

Option A (25.11.2026): the site repo github.com/dpgl77/dpgl_news is maintained
only by the assistant. This script no longer writes, commits or pushes
anything in the repo. On every run it:
  1. syncs the local clone to origin/main (git fetch + git reset --hard);
     uncommitted local edits are saved to _private/backup first;
  2. builds a PDF for every review / VVT / VTS page that has none, and rebuilds it
     when the page HTML changed (sha256 of the HTML kept in catalog.json);
  3. registers PDFs in _private/catalog.json and posts NEW reviews to the
     channel (an updated page is not posted again).
The «Скачать PDF» link, page headers, news_letter/index.html and sitemap.xml
are now put by the assistant before publishing.

Dry run (writes nothing; only `git fetch` updates remote refs):
    python publish_catalog.py --dry-run
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import register_pdf

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
PRIVATE = ROOT / "_private"
PDF_ROOT = PRIVATE / "pdf"
BACKUP_ROOT = PRIVATE / "backup"
LOCK_PATH = PRIVATE / "gate.lock"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CHANNEL = "@dpgl_news"
SKIP_DIRS = {"_private", "__pycache__"}
# VVT (equipment catalog) and VTS (military-technical cooperation by country)
# are catalogs opened from the site root. They stay inside news_letter so the
# published URLs stay valid; they are not news tabs and are never announced.
CATALOG_SKIP = {"VVT", "VTS"}
# PDFs built per run, so the bot keeps answering every 5 minutes. The first
# run after the update rebuilds all PDFs once (no hash stored yet) over
# several runs; pages whose HTML is newer than their PDF go first.
MAX_PDF_PER_RUN = 12
GATE_SCRIPTS = ("publish_catalog.py", "register_pdf.py", "telegram_gate.py", "register_tasks.ps1")


def git(*args, capture=True):
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=capture, text=True,
        encoding="utf-8", errors="replace", check=False,
    )


# ---------------------------------------------------------------- repo sync
def sync_repo(dry_run=False):
    """Make the local clone equal to origin/main. Returns True when synced."""
    fetched = git("fetch", "-q", "origin", "main")
    if fetched.returncode != 0:
        print("git: fetch failed, working with the local copy")
        return False
    own = [f"news_letter/{name}" for name in GATE_SCRIPTS]
    if git("diff", "--quiet", "origin/main", "--", *own).returncode != 0:
        # Never let a reset replace the running Gate with another version.
        print("git: Gate scripts here differ from GitHub, sync skipped. "
              "Install the same version in the repo (see README), then it syncs again.")
        return False
    dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    ahead = git("rev-list", "--count", "origin/main..HEAD").stdout.strip() or "0"
    behind = git("rev-list", "--count", "HEAD..origin/main").stdout.strip() or "0"
    if dry_run:
        print(f"git: behind origin/main {behind}, local commits not on GitHub {ahead}")
        if dirty:
            print("git: local edits that reset would discard (backup is saved first):")
            print(dirty)
        return True
    if dirty or ahead != "0":
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        if dirty:
            patch = git("diff", "HEAD").stdout
            (BACKUP_ROOT / f"local_edits_{stamp}.patch").write_text(patch, encoding="utf-8")
            print(f"git: local edits saved to _private/backup/local_edits_{stamp}.patch")
        if ahead != "0":
            commits = git("format-patch", "--stdout", "origin/main..HEAD").stdout
            (BACKUP_ROOT / f"local_commits_{stamp}.patch").write_text(commits, encoding="utf-8")
            print(f"git: {ahead} local commit(s) saved to _private/backup/local_commits_{stamp}.patch")
    git("checkout", "-q", "main")
    reset = git("reset", "-q", "--hard", "origin/main")
    if reset.returncode != 0:
        print("git: reset failed")
        return False
    if behind != "0" or ahead != "0" or dirty:
        print(f"git: synced to origin/main (+{behind} from GitHub)")
    return True


def tracked_html():
    """Pages tracked in git. Untracked local files are never turned into PDFs."""
    out = git("ls-files", "-z", "--", "news_letter").stdout
    return {name for name in out.split("\0") if name.endswith(".html")}


# ---------------------------------------------------------------- pages
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
    tracked = tracked_html()
    files = review_files() + equipment_files()
    if not tracked:
        return files
    return [path for path in files if path.relative_to(REPO).as_posix() in tracked]


def html_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- PDF
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


def pdf_plan():
    """List of (path, relative, reason, sha) that need a PDF build, in build order."""
    state = register_pdf.load_state().get("files", {})
    missing, changed, unhashed = [], [], []
    for path in pdf_source_files():
        relative = path.relative_to(ROOT).as_posix()
        destination = PDF_ROOT / Path(relative).with_suffix(".pdf")
        sha = html_sha256(path)
        known = state.get(relative, {}).get("html_sha256")
        if not destination.exists() or destination.stat().st_size <= 1000:
            missing.append((path, relative, "new", sha))
        elif known is None:
            age = path.stat().st_mtime - destination.stat().st_mtime
            unhashed.append((age, (path, relative, "no hash yet", sha)))
        elif known != sha:
            changed.append((path, relative, "page changed", sha))
    unhashed.sort(key=lambda item: item[0], reverse=True)  # HTML newer than PDF first
    return missing + changed + [item for _, item in unhashed]


def remember_hash(relative, sha):
    state = register_pdf.load_state()
    files = state.setdefault("files", {})
    files.setdefault(relative, {})["html_sha256"] = sha
    register_pdf.save_state(state)


def build_pdfs():
    browser = EDGE if EDGE.exists() else CHROME
    built = []
    if not browser.exists():
        print("pdf: browser not found")
        return built
    plan = pdf_plan()
    if len(plan) > MAX_PDF_PER_RUN:
        print(f"pdf: {len(plan)} to build, {MAX_PDF_PER_RUN} this run, the rest next runs")
    for path, relative, reason, sha in plan[:MAX_PDF_PER_RUN]:
        destination = PDF_ROOT / Path(relative).with_suffix(".pdf")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_pdf = destination.with_suffix(".tmp.pdf")
        profile = Path(tempfile.mkdtemp(prefix="dpgl-pdf-"))
        temp_html = destination.with_suffix(".print.html")
        temp_html.write_text(printable_html(path.read_text(encoding="utf-8")), encoding="utf-8")
        if temp_pdf.exists():
            temp_pdf.unlink()
        command = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            "--no-pdf-header-footer",
            "--virtual-time-budget=30000",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={temp_pdf}",
            temp_html.resolve().as_uri(),
        ]
        try:
            if LOCK_PATH.exists():
                LOCK_PATH.touch()
            subprocess.run(command, check=False, timeout=240, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            pass
        finally:
            if temp_html.exists():
                temp_html.unlink()
            shutil.rmtree(profile, ignore_errors=True)
        if temp_pdf.exists() and temp_pdf.stat().st_size > 1000:
            # The old PDF stays in place until the new one is ready.
            os.replace(temp_pdf, destination)
            remember_hash(relative, sha)
            built.append(relative)
            print(f"pdf ({reason}): {relative}")
        else:
            if temp_pdf.exists():
                temp_pdf.unlink()
            print(f"pdf failed: {relative}")
    return built


# ---------------------------------------------------------------- channel
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
    # register() keeps telegram_posted=True for pages already announced, so an
    # updated page (new PDF) is not posted again. Only new reviews are posted.
    pending = register_pdf.register(False) or []
    posted = []
    for item in pending:
        if send_channel(bot_token, item["text"]):
            register_pdf.mark_posted(item["token"])
            posted.append(item["relative"])
    return posted


# ---------------------------------------------------------------- entry points
def publish_new(bot_token):
    synced = sync_repo()
    built = build_pdfs()
    posted = announce_new(bot_token) if bot_token else []
    print(f"catalog: synced {synced}, pdf {len(built)}, posted {len(posted)}")


def dry_run():
    print("DRY RUN: nothing is written, built, posted or committed")
    sync_repo(dry_run=True)
    print("note: the list below is for the current local files; a real run resets them to origin/main first")
    plan = pdf_plan()
    print(f"pdf: {len(plan)} to build ({MAX_PDF_PER_RUN} per run)")
    for _path, relative, reason, _sha in plan:
        print(f"  {reason}: {relative}")
    state = register_pdf.load_state().get("files", {})
    new = [
        path.relative_to(ROOT).as_posix() for path in pdf_source_files()
        if path.parent.name not in CATALOG_SKIP
        and not state.get(path.relative_to(ROOT).as_posix(), {}).get("telegram_posted")
    ]
    print(f"channel: {len(new)} new review(s) would be posted after their PDF is built")
    for relative in new:
        print(f"  {relative}")
    print(f"git: the Gate does not commit or push (option A)")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="show what a run would do")
    parser.add_argument("--sync-index", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sync_index:
        raise SystemExit("--sync-index removed: news_letter/index.html is maintained by the assistant (option A)")
    if args.dry_run:
        dry_run()
        return
    raise SystemExit("usage: publish_catalog.py --dry-run   (normal runs start from telegram_gate.py)")


if __name__ == "__main__":
    main()

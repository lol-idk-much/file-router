import os
import sys
import time
import shutil
import subprocess
import zipfile
import re
import html
from datetime import datetime

def parse_and_import_takeout(zip_path, vault_dir, logger=None):
    attach_dir = os.path.join(vault_dir, "Attachments")
    os.makedirs(vault_dir, exist_ok=True)
    os.makedirs(attach_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as z:
        # 1. Extract attachments
        for member in z.namelist():
            if member.endswith("/") or "MyActivity." in member:
                continue
            fname = os.path.basename(member)
            if not fname or fname.startswith("."):
                continue
            target_path = os.path.join(attach_dir, fname)
            if not os.path.exists(target_path):
                with z.open(member) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        # 2. Parse HTML & JSON activity
        html_files = [m for m in z.namelist() if m.endswith("MyActivity.html") and "Gemini" in m]
        if not html_files:
            html_files = [m for m in z.namelist() if m.endswith("MyActivity.html")]

        if not html_files:
            return

        raw_html = z.read(html_files[0]).decode('utf-8', errors='ignore')

    cells = re.findall(r'<div class="outer-cell mdl-cell mdl-cell--12-col[^"]*">(.*?)</div>\s*</div>\s*</div>', raw_html, re.DOTALL)
    
    def html_to_md(text):
        text = re.sub(r'<pre><code>(.*?)</code></pre>', lambda m: f"\n```\n{html.unescape(m.group(1))}\n```\n", text, flags=re.DOTALL)
        text = re.sub(r'<code>(.*?)</code>', lambda m: f"`{html.unescape(m.group(1))}`", text, flags=re.DOTALL)
        text = re.sub(r'<h3>(.*?)</h3>', r'\n### \1\n', text)
        text = re.sub(r'<h2>(.*?)</h2>', r'\n## \1\n', text)
        text = re.sub(r'<p>(.*?)</p>', r'\n\1\n', text, flags=re.DOTALL)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'<li>(.*?)</li>', r'* \1', text, flags=re.DOTALL)
        text = re.sub(r'<b>(.*?)</b>', r'**\1**', text)
        text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text)
        text = re.sub(r'<i>(.*?)</i>', r'*\1*', text)
        text = re.sub(r'<em>(.*?)</em>', r'*\1*', text)
        text = re.sub(r'<a href="([^"]+)">(.*?)</a>', r'[\2](\1)', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    parsed_events = []
    date_pattern = re.compile(r'([A-Za-z]{3}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM|am|pm)?\s*(?:EDT|EST|UTC|GMT|PDT|PST)?)')

    for cell in cells:
        content_match = re.search(r'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">(.*?)</div>', cell, re.DOTALL)
        if not content_match:
            continue
        raw_content = content_match.group(1)
        date_match = date_pattern.search(raw_content)
        if not date_match:
            continue
        date_str = date_match.group(1)
        
        dt = None
        cleaned_date = re.sub(r'\s+(?:EDT|EST|PDT|PST|UTC|GMT)$', '', date_str).strip()
        for fmt in ["%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S", "%B %d, %Y, %I:%M:%S %p"]:
            try:
                dt = datetime.strptime(cleaned_date, fmt)
                break
            except Exception:
                pass
        if not dt:
            continue

        iso_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        day_key = dt.strftime("%Y-%m-%d")
        
        parts = raw_content.split(date_str, 1)
        user_part = parts[0]
        gemini_part = parts[1] if len(parts) > 1 else ""
        
        user_prompt = html_to_md(user_part)
        if user_prompt.startswith("Prompted"): user_prompt = user_prompt[8:].strip()
        elif user_prompt.startswith("Said"): user_prompt = user_prompt[4:].strip()
        gemini_resp = html_to_md(gemini_part)
        
        if user_prompt or gemini_resp:
            parsed_events.append({
                "dt": dt,
                "iso_time": iso_time,
                "day_key": day_key,
                "user_prompt": user_prompt,
                "gemini_response": gemini_resp
            })

    parsed_events.sort(key=lambda x: x["dt"])
    by_day = {}
    for ev in parsed_events:
        by_day.setdefault(ev["day_key"], []).append(ev)

    for day_key, events in by_day.items():
        existing_files = [f for f in os.listdir(vault_dir) if f.startswith(f"Gemini_{day_key}") and f.endswith(".md")]
        if existing_files:
            target_file = os.path.join(vault_dir, existing_files[0])
            with open(target_file, "r", encoding="utf-8") as f:
                existing_content = f.read()
        else:
            first_time = events[0]["dt"].strftime("%Y-%m-%d_%H%M%S")
            target_file = os.path.join(vault_dir, f"Gemini_{first_time}_Daily_Thread_{day_key}.md")
            existing_content = ""

        lines_to_append = []
        for ev in events:
            time_tag = f"### User ({ev['iso_time']})"
            if time_tag in existing_content or (ev["user_prompt"] and ev["user_prompt"][:60] in existing_content):
                continue
            block = [f"### User ({ev['iso_time']})\n{ev['user_prompt']}\n"]
            if ev["gemini_response"]:
                block.append(f"### Gemini\n{ev['gemini_response']}\n")
            lines_to_append.append("\n".join(block))

        if lines_to_append:
            with open(target_file, "a" if existing_content else "w", encoding="utf-8") as f:
                if not existing_content:
                    f.write(f"---\ntags: [ai, gemini, takeout]\ndate: {day_key}\n---\n\n")
                else:
                    f.write("\n\n")
                f.write("\n\n".join(lines_to_append))


def organize_vault_by_rolling_month(vault_dir, rolling_days=8, max_active_months=2):
    """
    Organizes older chat notes into YYYY-MM folders and Year folders.
    - Keeps the last `rolling_days` (default 8) at the root of AI_Chats.
    - Keeps only `max_active_months` (default 2, e.g. current and previous month) as top-level month folders.
    - Archives all earlier months into YYYY/YYYY-MM folders.
    """
    from datetime import date, timedelta
    today = date.today()
    cutoff_date = today - timedelta(days=rolling_days)
    exclude_dirs = {"Attachments", "Artifacts", ".git"}
    date_regex = re.compile(r'(\d{4})-(\d{2})-(\d{2})')

    # Calculate active month strings (e.g. ['2026-09', '2026-08'])
    active_months = set()
    d = today.replace(day=1)
    for _ in range(max_active_months):
        active_months.add(f"{d.year:04d}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)

    def get_target_folder(note_date):
        ym = f"{note_date.year:04d}-{note_date.month:02d}"
        if ym in active_months:
            return os.path.join(vault_dir, ym)
        return os.path.join(vault_dir, f"{note_date.year:04d}", ym)

    # 1. Gather and move all md files
    for root, dirs, files in os.walk(vault_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if not f.endswith(".md"):
                continue
            fpath = os.path.join(root, f)
            m = date_regex.search(f)
            if not m:
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as note_f:
                        m = date_regex.search(note_f.read(500))
                except Exception:
                    pass
            if not m:
                continue

            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                note_date = date(year, month, day)
            except ValueError:
                continue

            if note_date >= cutoff_date:
                dest = os.path.join(vault_dir, f)
            else:
                target_dir = get_target_folder(note_date)
                os.makedirs(target_dir, exist_ok=True)
                dest = os.path.join(target_dir, f)

            if os.path.abspath(fpath) != os.path.abspath(dest):
                shutil.move(fpath, dest)

    # 2. Move older top-level month folders into Year folder
    for item in os.listdir(vault_dir):
        item_path = os.path.join(vault_dir, item)
        if not os.path.isdir(item_path) or item in exclude_dirs or re.match(r'^\d{4}$', item):
            continue
        if re.match(r'^\d{4}-\d{2}$', item):
            if item not in active_months:
                year_str = item[:4]
                year_dir = os.path.join(vault_dir, year_str)
                os.makedirs(year_dir, exist_ok=True)
                target_path = os.path.join(year_dir, item)
                if not os.path.exists(target_path):
                    shutil.move(item_path, target_path)
                else:
                    for sub in os.listdir(item_path):
                        shutil.move(os.path.join(item_path, sub), os.path.join(target_path, sub))
                    os.rmdir(item_path)

    # 3. Clean empty directories
    for root, dirs, files in os.walk(vault_dir, topdown=False):
        if os.path.basename(root) in exclude_dirs or root == vault_dir:
            continue
        if not os.listdir(root):
            os.rmdir(root)

def handle_gemini_takeout(src_path, target_vault_dir, archive_dir, min_age_sec, dry_run, logger):
    filename = os.path.basename(src_path)
    try:
        age = time.time() - os.path.getmtime(src_path)
        if age < min_age_sec:
            return False
    except Exception:
        return False

    logger.info(f"Processing Gemini Takeout archive: {filename}")
    if dry_run:
        logger.info(f"[DRY-RUN] Would extract {filename}, parse to {target_vault_dir}, and archive to {archive_dir}")
        return True

    try:
        parse_and_import_takeout(src_path, target_vault_dir, logger)
        organize_vault_by_rolling_month(target_vault_dir, rolling_days=8)
        logger.info("Parsed Gemini Takeout into Obsidian Vault and organized by month.")

        vault_root = os.path.expanduser("~/Documents/Vault")
        subprocess.run(["git", "-C", vault_root, "add", "-A"], check=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(["git", "-C", vault_root, "commit", "-m", f"Auto-import Gemini Takeout ({now_str})"], check=False)
        subprocess.run(["git", "-C", vault_root, "push", "origin", "main"], check=False)
        logger.info("Vault git commit and push completed.")
    except Exception as e:
        logger.error(f"Error parsing takeout archive: {e}")

    archive_dir_exp = os.path.expanduser(archive_dir)
    if os.path.exists(archive_dir_exp):
        dest_zip = os.path.join(archive_dir_exp, filename)
        with open(src_path, "rb") as f_in, open(dest_zip, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out, length=2 * 1024 * 1024)
        os.remove(src_path)
        logger.info(f"Archived {filename} -> {dest_zip}")
    return True

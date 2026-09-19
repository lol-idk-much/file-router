import os
import time
import shutil
import fnmatch

def should_exclude(rel_path, filename, excludes):
    if filename.startswith(".DS_Store") or filename.endswith(".tmp") or filename.endswith(".bak"):
        return True
    for pat in excludes:
        if fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(rel_path, pat):
            return True
    return False

def matches_patterns(filename, patterns):
    if not patterns or "*" in patterns:
        return True
    for pat in patterns:
        if fnmatch.fnmatch(filename, pat):
            return True
    return False

def sync_single_file(src_path, dest_path, dry_run, logger):
    """
    Pure byte-streaming copy that updates dest if modified or missing.
    Bypasses macOS SMB extended attributes / ACLs that trigger Errno 1.
    """
    try:
        src_stat = os.stat(src_path)
        src_size = src_stat.st_size
        src_mtime = src_stat.st_mtime

        if os.path.exists(dest_path):
            dest_stat = os.stat(dest_path)
            dest_size = dest_stat.st_size
            dest_mtime = dest_stat.st_mtime

            # If identical size and mtime within 2 seconds, already in sync
            if dest_size == src_size and abs(dest_mtime - src_mtime) < 2:
                return False

        if dry_run:
            logger.info(f"[DRY-RUN] Would mirror: {os.path.basename(src_path)} -> {dest_path}")
            return True

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        with open(src_path, "rb") as f_src, open(dest_path, "wb") as f_dest:
            shutil.copyfileobj(f_src, f_dest, length=1024 * 1024)

        # Sync mtime
        try:
            os.utime(dest_path, (src_mtime, src_mtime))
        except Exception:
            pass

        logger.info(f"Mirrored: {os.path.basename(src_path)} ({src_size} bytes) -> {dest_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to mirror {src_path}: {e}")
        return False

def sync_mirror(src_dir, dest_dir, patterns=None, excludes=None, delete_orphaned=False, dry_run=False, logger=None):
    """
    One-way mirror sync from src_dir to dest_dir.
    Safely skips if remote destination mount is unavailable.
    """
    if not os.path.exists(src_dir):
        return 0

    # Safety check for remote /Volumes/ mount
    if dest_dir.startswith("/Volumes/"):
        vol_name = "/" + "/".join(dest_dir.strip("/").split("/")[:2])
        if not os.path.exists(vol_name):
            if logger:
                logger.debug(f"Volume '{vol_name}' not mounted. Skipping mirror sync.")
            return 0

    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        if logger:
            logger.warning(f"Could not access/create destination {dest_dir}: {e}")
        return 0

    if excludes is None:
        excludes = [".DS_Store", "*.log", "*.sqlite", "*.tmp", "*.bak", "Macbook"]

    synced_count = 0
    all_src_rel_paths = set()

    for root, dirs, files in os.walk(src_dir):
        # Prune excluded directories
        rel_root = os.path.relpath(root, src_dir)
        if rel_root == ".":
            rel_root = ""

        # Filter dirs in-place to avoid descending into excluded ones
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(rel_root, d), d, excludes)]

        for fname in files:
            rel_file = os.path.normpath(os.path.join(rel_root, fname))
            if should_exclude(rel_file, fname, excludes):
                continue

            # Check pattern filter for top-level files
            if rel_root == "" and not matches_patterns(fname, patterns):
                continue

            all_src_rel_paths.add(rel_file)
            src_file_path = os.path.join(root, fname)
            dest_file_path = os.path.join(dest_dir, rel_file)

            if sync_single_file(src_file_path, dest_file_path, dry_run, logger):
                synced_count += 1

    # Optionally clean up files deleted on source
    if delete_orphaned and os.path.exists(dest_dir):
        for root, dirs, files in os.walk(dest_dir):
            rel_root = os.path.relpath(root, dest_dir)
            if rel_root == ".":
                rel_root = ""

            for fname in files:
                rel_file = os.path.normpath(os.path.join(rel_root, fname))
                if should_exclude(rel_file, fname, excludes):
                    continue

                if rel_file not in all_src_rel_paths:
                    orphan_path = os.path.join(root, fname)
                    if dry_run:
                        if logger:
                            logger.info(f"[DRY-RUN] Would remove orphaned file from mirror: {orphan_path}")
                    else:
                        try:
                            os.remove(orphan_path)
                            if logger:
                                logger.info(f"Removed orphaned file from mirror: {rel_file}")
                        except Exception as e:
                            if logger:
                                logger.error(f"Failed to remove orphan {orphan_path}: {e}")

    if synced_count > 0 and not dry_run:
        try:
            import subprocess
            git_check = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=dest_dir,
                capture_output=True,
                text=True
            )
            if git_check.returncode == 0:
                repo_root = git_check.stdout.strip()
                subprocess.run(["git", "add", "-A"], cwd=repo_root, capture_output=True)
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                commit_res = subprocess.run(
                    ["git", "commit", "-m", f"Auto-sync Surge profiles - {timestamp}"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True
                )
                if commit_res.returncode == 0 and logger:
                    logger.info(f"Git auto-committed Surge updates to {repo_root}")
        except Exception as e:
            if logger:
                logger.debug(f"Git auto-commit skipped: {e}")

    return synced_count

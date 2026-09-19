#!/usr/bin/env python3
import os
import sys
import glob
import time
import logging
import argparse
from datetime import datetime

# Add current script dir to sys.path so handlers package is importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from handlers import move_verified, cleanup_retention, handle_gemini_takeout, sync_mirror

CONFIG_PATH = os.environ.get("FILE_ROUTER_CONFIG", os.path.expanduser("~/programs/file_router/config.yaml"))

def load_config(path):
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[FATAL] Failed to load config {path}: {e}", file=sys.stderr)
        sys.exit(1)

def setup_logger(log_file, verbose=False):
    log_path = os.path.expanduser(log_file)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger("FileRouter")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    # File handler
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger

def show_status(config, cfg_path):
    nas_status = "MOUNTED" if os.path.exists("/Volumes/Media") else "UNMOUNTED"
    print("=== FileRouter Status ===")
    print(f"Config: {cfg_path}")
    print(f"NAS Mount (/Volumes/Media): {nas_status}\nRules:")
    for r in config.get("rules", []):
        r_name = r.get("name", "Unnamed")
        r_enabled = "ENABLED" if r.get("enabled") else "DISABLED"
        action = r.get("action", "move_verified")
        
        if action == "cleanup_retention":
            tgt = os.path.expanduser(r.get("target", ""))
            print(f"- {r_name}: [{r_enabled}] Retention on {tgt}")
        else:
            src = os.path.expanduser(r.get("source", ""))
            tgt = os.path.expanduser(r.get("target", ""))
            count = len([f for f in glob.glob(os.path.join(src, "*")) if os.path.isfile(f)]) if os.path.exists(src) else 0
            print(f"- {r_name}: [{r_enabled}] Items: {count} in {src} -> {tgt}")

def show_recent_logs(log_file, lines_count=25):
    log_path = os.path.expanduser(log_file)
    if not os.path.exists(log_path):
        print(f"No log file found at {log_path}")
        return
    print(f"=== Last {lines_count} lines of {log_path} ===")
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        for line in lines[-lines_count:]:
            sys.stdout.write(line)

def show_recent_errors(log_file):
    log_path = os.path.expanduser(log_file)
    if not os.path.exists(log_path):
        print(f"No log file found at {log_path}")
        return
    print(f"=== Active / Recent Errors in {log_path} ===")
    error_lines = []
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "[ERROR]" in line:
                error_lines.append(line.strip())
    if not error_lines:
        print("No errors recorded. All systems clean!")
    else:
        for line in error_lines[-15:]:
            print(line)

def sync_launchd_watchpaths(config, logger=None):
    if not config.get("settings", {}).get("sync_launchd_watchpaths", False):
        return
    plist_path = os.path.expanduser("~/Library/LaunchAgents/com.user.filerouter.plist")
    if not os.path.exists(plist_path):
        return
    try:
        import plistlib
        sources = set()
        for rule in config.get("rules", []):
            if rule.get("enabled", True):
                src = rule.get("source")
                if src:
                    expanded = os.path.abspath(os.path.expanduser(src))
                    if os.path.exists(expanded) and not expanded.startswith("/Volumes/"):
                        sources.add(expanded)

        sorted_sources = sorted(sources)
        with open(plist_path, "rb") as f:
            plist_data = plistlib.load(f)

        current_watch = plist_data.get("WatchPaths", [])
        if sorted(current_watch) != sorted_sources:
            plist_data["WatchPaths"] = sorted_sources
            with open(plist_path, "wb") as f:
                plistlib.dump(plist_data, f)
            if logger:
                logger.info(f"Dynamically updated Launchd WatchPaths in {plist_path}: {sorted_sources}")
    except Exception as e:
        if logger:
            logger.warning(f"Failed to synchronize launchd WatchPaths: {e}")

def run_router(config, dry_run=False, verbose=False):
    settings = config.get("settings", {})
    log_file = settings.get("log_file", "~/Library/Logs/FileRouter/file_router.log")
    logger = setup_logger(log_file, verbose=verbose)
    default_min_age = settings.get("default_min_age_seconds", 3)

    if not dry_run:
        sync_launchd_watchpaths(config, logger)

    rules = config.get("rules", [])
    total_processed = 0

    for rule in rules:
        if not rule.get("enabled", True):
            continue

        rule_name = rule.get("name", "Unnamed Rule")
        action = rule.get("action", "move_verified")
        target_dir = os.path.expanduser(rule.get("target", ""))

        # Check target network mount if applicable
        if target_dir.startswith("/Volumes/") and not os.path.exists(target_dir):
            vol_name = "/" + "/".join(target_dir.strip("/").split("/")[:2])
            if not os.path.exists(vol_name):
                if verbose:
                    logger.debug(f"Skipping rule '{rule_name}': Volume '{vol_name}' is offline.")
                continue

        if action == "cleanup_retention":
            retention_rules = rule.get("retention_rules", [{"max_age_days": 30}])
            cleaned = cleanup_retention(target_dir, retention_rules, dry_run, logger)
            total_processed += cleaned
            continue

        if action == "sync_mirror":
            patterns = rule.get("patterns", ["*"])
            excludes = rule.get("excludes", None)
            delete_orphaned = rule.get("delete_orphaned", False)
            source_dir = os.path.expanduser(rule.get("source", ""))
            synced = sync_mirror(source_dir, target_dir, patterns=patterns, excludes=excludes, delete_orphaned=delete_orphaned, dry_run=dry_run, logger=logger)
            total_processed += synced
            continue

        source_dir = os.path.expanduser(rule.get("source", ""))
        if not os.path.exists(source_dir):
            if verbose:
                logger.warning(f"Rule '{rule_name}': Source directory missing: {source_dir}")
            continue

        patterns = rule.get("patterns", ["*"])
        excludes = rule.get("excludes", [])
        min_age = rule.get("min_age_seconds", default_min_age)
        recursive = rule.get("recursive", False)
        cleanup_empty_dirs = rule.get("cleanup_empty_dirs", False)

        import fnmatch
        candidate_files = []
        if recursive:
            for root, dirs, files in os.walk(source_dir):
                for fname in files:
                    if any(fnmatch.fnmatch(fname, pat) for pat in patterns):
                        if not any(fnmatch.fnmatch(fname, exc) for exc in excludes):
                            candidate_files.append(os.path.join(root, fname))
        else:
            for pat in patterns:
                candidate_files.extend(glob.glob(os.path.join(source_dir, pat)))
            if excludes:
                candidate_files = [f for f in candidate_files if not any(fnmatch.fnmatch(os.path.basename(f), exc) for exc in excludes)]

        for fpath in sorted(set(candidate_files)):
            if not os.path.isfile(fpath):
                continue

            if action == "move_verified":
                if move_verified(fpath, target_dir, min_age, dry_run, logger):
                    total_processed += 1
            elif action == "import_gemini_takeout":
                archive_dir = rule.get("archive_dir", "/Volumes/Media/Rick/DocumentsNAS/Other")
                if handle_gemini_takeout(fpath, target_dir, archive_dir, min_age, dry_run, logger):
                    total_processed += 1

        # Clean up empty subdirectories left behind if requested
        if recursive and cleanup_empty_dirs and not dry_run:
            for root, dirs, files in os.walk(source_dir, topdown=False):
                if os.path.abspath(root) == os.path.abspath(source_dir):
                    continue
                # Ignore macOS metadata files when checking emptiness
                entries = [e for e in os.listdir(root) if e not in [".DS_Store", "desktop.ini"] and not e.startswith("._")]
                if not entries:
                    try:
                        for junk in os.listdir(root):
                            os.remove(os.path.join(root, junk))
                        os.rmdir(root)
                        if verbose:
                            logger.debug(f"Removed empty directory: {root}")
                    except Exception as e:
                        logger.debug(f"Could not remove directory {root}: {e}")

    # Execute post-run hooks if configured
    hooks = config.get("hooks", {})
    post_run_commands = hooks.get("post_run", [])
    for cmd_str in post_run_commands:
        try:
            import subprocess
            if verbose:
                logger.debug(f"Executing post-run hook: {cmd_str}")
            res = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                if res.stdout.strip() and verbose:
                    logger.debug(f"Hook output: {res.stdout.strip()}")
            else:
                logger.warning(f"Post-run hook failed (code {res.returncode}): {res.stderr.strip()}")
        except Exception as e:
            logger.warning(f"Failed to execute post-run hook '{cmd_str}': {e}")

    if total_processed > 0 or verbose:
        logger.info(f"FileRouter finished. Processed {total_processed} files.")
    return total_processed

def main():
    parser = argparse.ArgumentParser(description="Declarative File Routing Engine for macOS")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "status", "dry-run", "log", "errors", "watch"],
                        help="Command to execute (default: run)")
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to config.yaml")
    parser.add_argument("--run", dest="flag_run", action="store_true", help="Process rules once and exit")
    parser.add_argument("--dry-run", dest="flag_dry_run", action="store_true", help="Preview moves without modifying files")
    parser.add_argument("--status", dest="flag_status", action="store_true", help="Show system status and mount health")
    parser.add_argument("--log", dest="flag_log", action="store_true", help="Show recent logs")
    parser.add_argument("--errors", dest="flag_errors", action="store_true", help="Show recent error history")
    parser.add_argument("--watch", dest="flag_watch", action="store_true", help="Run in continuous loop (15s)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose/debug logging")
    args = parser.parse_args()

    # Normalize command whether user used `file-router status` or `file-router --status`
    cmd = args.command
    if args.flag_status: cmd = "status"
    elif args.flag_dry_run: cmd = "dry-run"
    elif args.flag_log: cmd = "log"
    elif args.flag_errors: cmd = "errors"
    elif args.flag_watch: cmd = "watch"
    elif args.flag_run: cmd = "run"

    cfg_path = os.path.expanduser(args.config)
    if not os.path.exists(cfg_path):
        print(f"Error: Config not found at {cfg_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(cfg_path)
    log_file = config.get("settings", {}).get("log_file", "~/Library/Logs/FileRouter/file_router.log")

    if cmd == "status":
        show_status(config, cfg_path)
        sys.exit(0)
    elif cmd == "log":
        show_recent_logs(log_file)
        sys.exit(0)
    elif cmd == "errors":
        show_recent_errors(log_file)
        sys.exit(0)
    elif cmd == "watch":
        print("Running in watch mode (Ctrl+C to stop)...")
        while True:
            run_router(config, dry_run=False, verbose=args.verbose)
            time.sleep(15)
    elif cmd == "dry-run":
        run_router(config, dry_run=True, verbose=args.verbose)
        sys.exit(0)
    else: # run
        run_router(config, dry_run=False, verbose=args.verbose)

if __name__ == "__main__":
    main()

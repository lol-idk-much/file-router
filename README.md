# FileRouter

A lightweight, declarative, automated file routing and archiving engine for macOS.

FileRouter continuously monitors directories, evaluates rule-based criteria, and applies atomic handlers (byte-streamed moves across network shares/SMB, deduplication, retention cleanup, directory mirroring, and custom hooks).

## Key Features

- **Declarative YAML Rules**: Define sources, targets, glob patterns, file age thresholds, and actions cleanly.
- **Safe Network Moves (`move_verified`)**: Uses pure Python chunked byte streaming (`copyfileobj`) to prevent macOS SMB extended attribute/ACL (`Errno 1 Operation not permitted`) crashes. Verifies destination existence and byte size before removing the source.
- **Single File Extraction (`recursive: true`)**: Recursively finds matching file types (e.g. `*.dmg`, `*.iso`) inside nested package directories, moves **only** the matching files to the target, and leaves non-matching files untouched.
- **Orphan Directory Cleanup (`cleanup_empty_dirs: true`)**: Cleans up empty parent directories left behind after files are extracted, safely ignoring macOS metadata (`.DS_Store`, `._*`).
- **Retention Policies (`cleanup_retention`)**: Automatically prunes aging files (e.g. temporary screenshots or recordings older than N days, with optional minimum size thresholds).
- **Directory Mirroring (`sync_mirror`)**: Keeps local directories synchronized with remote/backup shares, with exclusion filters.
- **Post-Run Hooks (`hooks.post_run`)**: Trigger custom notification scripts or external tools after each routing cycle.
- **Native launchd Integration**: Dynamically keeps `com.user.filerouter.plist` watch paths in sync with enabled rules.

---

## Installation

### 1. Prerequisites
- macOS 12+
- Python 3.9+

### 2. Setup
```bash
git clone https://github.com/lol-idk-much/file-router.git ~/programs/file_router
cd ~/programs/file_router

# Create virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration
Copy the template configuration:
```bash
cp config.example.yaml config.yaml
```
Edit `config.yaml` to specify your rules and paths.

---

## CLI Commands

```bash
# Process rules once
file-router run
file-router --run

# Preview actions without moving or deleting any files
file-router dry-run
file-router --dry-run

# Show rules, source counts, and volume mount status
file-router status
file-router --status

# View recent log entries
file-router log
file-router --log

# View recent error history
file-router errors
file-router --errors

# Run continuously in foreground (15s poll loop)
file-router watch
file-router --watch
```

---

## LaunchAgent Service Setup

To run FileRouter automatically in the background on macOS:

1. Copy the plist template:
   ```bash
   cp com.user.filerouter.plist.example ~/Library/LaunchAgents/com.user.filerouter.plist
   ```
2. Adjust the paths in `~/Library/LaunchAgents/com.user.filerouter.plist` to point to your user directory and `run.sh`.
3. Load the service:
   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.filerouter.plist
   ```

---

## License

MIT License

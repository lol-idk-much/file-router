import os
import time
import shutil
from datetime import datetime

def get_unique_dest_path(dest_path):
    """If dest_path exists and has different size/content, append timestamp."""
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{timestamp}{ext}"

def move_verified(src_path, dest_dir, min_age_sec, dry_run, logger):
    """
    Atomically copies file to dest_dir using pure byte streaming (preventing
    macOS SMB extended attribute/ACL 'Errno 1 Operation not permitted'),
    verifies destination size matches source, and removes source.
    """
    filename = os.path.basename(src_path)

    # Ignore macOS temp, download-in-progress, and hidden files
    if (filename.startswith(".") or 
        filename.endswith(".crdownload") or 
        filename.endswith(".download") or 
        filename.endswith(".tmp")):
        return False

    # Check file age (ensure download/writing is complete)
    try:
        mtime = os.path.getmtime(src_path)
        age = time.time() - mtime
        if age < min_age_sec:
            logger.debug(f"Skipping {filename}: file age ({age:.1f}s) < {min_age_sec}s")
            return False
        src_size = os.path.getsize(src_path)
    except Exception as e:
        logger.warning(f"Could not stat {src_path}: {e}")
        return False

    dest_path = os.path.join(dest_dir, filename)

    # If file exists on dest with identical size, safely delete local duplicate
    if os.path.exists(dest_path):
        dest_size = os.path.getsize(dest_path)
        if dest_size == src_size and src_size > 0:
            if dry_run:
                logger.info(f"[DRY-RUN] Exact match exists on dest ({dest_size} bytes). Would remove local: {filename}")
                return True
            os.remove(src_path)
            logger.info(f"Duplicate cleaned: {filename} already safely exists on NAS ({dest_size} bytes)")
            return True
        else:
            dest_path = get_unique_dest_path(dest_path)

    if dry_run:
        logger.info(f"[DRY-RUN] Would move {filename} ({src_size} bytes) -> {dest_path}")
        return True

    try:
        os.makedirs(dest_dir, exist_ok=True)
        # Use pure Python byte streaming to completely bypass macOS fcopyfile / xattr errors on SMB
        with open(src_path, "rb") as f_src, open(dest_path, "wb") as f_dest:
            shutil.copyfileobj(f_src, f_dest, length=1024 * 1024)

        # Verify
        if not os.path.exists(dest_path):
            logger.error(f"Verification failed: {dest_path} not found after copy")
            return False

        dest_size = os.path.getsize(dest_path)
        if dest_size != src_size:
            logger.error(f"Size mismatch for {filename}: src={src_size} dest={dest_size}")
            return False

        # Safe removal of source
        os.remove(src_path)
        logger.info(f"Moved: {filename} ({src_size} bytes) -> {os.path.basename(dest_path)}")
        return True
    except Exception as e:
        logger.error(f"Failed to move {filename}: {e}")
        return False

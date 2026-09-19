import os
import time

def cleanup_retention(target_dir, retention_rules, dry_run, logger):
    """
    Cleans up old files based on retention policies:
    - Default: age > 30 days -> remove
    - Large files: size > 125MB and age > 14 days -> remove
    """
    if not os.path.exists(target_dir):
        return 0

    now = time.time()
    day_seconds = 86400
    cleaned_count = 0

    try:
        filenames = os.listdir(target_dir)
    except Exception as e:
        logger.warning(f"Cannot access {target_dir} for retention cleanup: {e}")
        return 0

    for fname in filenames:
        if fname.startswith("."):
            continue

        fpath = os.path.join(target_dir, fname)
        if not os.path.isfile(fpath):
            continue

        try:
            stat = os.stat(fpath)
            age_days = (now - stat.st_mtime) / day_seconds
            size_mb = stat.st_size / (1024 * 1024)

            should_delete = False
            reason = ""

            for rule in retention_rules:
                max_days = rule.get("max_age_days", 30)
                min_size = rule.get("min_size_mb", None)

                if min_size is not None:
                    if size_mb >= min_size and age_days >= max_days:
                        should_delete = True
                        reason = f"Large file ({size_mb:.1f}MB >= {min_size}MB) older than {max_days} days (age: {age_days:.1f}d)"
                        break
                else:
                    if age_days >= max_days:
                        should_delete = True
                        reason = f"File older than {max_days} days (age: {age_days:.1f}d)"
                        break

            if should_delete:
                if dry_run:
                    logger.info(f"[DRY-RUN] Would delete {fname}: {reason}")
                    cleaned_count += 1
                else:
                    # Move to Trash if local, or unlink directly if on remote SMB share
                    try:
                        os.remove(fpath)
                        logger.info(f"Cleaned ({reason}): {fname}")
                        cleaned_count += 1
                    except Exception as e:
                        logger.error(f"Failed to delete {fname}: {e}")

        except Exception as e:
            logger.warning(f"Could not check retention for {fname}: {e}")

    return cleaned_count

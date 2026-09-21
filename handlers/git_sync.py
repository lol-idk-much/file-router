import os
import subprocess
from datetime import datetime

def sync_git_repo(repo_path, branch="main", remote="origin", commit_prefix="auto-sync", logger=None):
    """
    Safely pulls, commits, and pushes a Git repository.
    Returns:
        1 if changes were committed or pushed, 0 otherwise.
    """
    expanded = os.path.abspath(os.path.expanduser(repo_path))
    git_dir = os.path.join(expanded, ".git")
    repo_name = os.path.basename(expanded)

    if not os.path.exists(git_dir):
        if logger:
            logger.warning(f"git_sync ({repo_name}): Not a git repository: {expanded}")
        return 0

    def run_git(args):
        return subprocess.run(
            ["git", "-C", expanded] + args,
            capture_output=True,
            text=True,
            timeout=30
        )

    try:
        # 1. Fetch remote changes
        res_fetch = run_git(["fetch", remote, branch])
        if res_fetch.returncode != 0 and logger:
            logger.debug(f"git_sync ({repo_name}): fetch warning: {res_fetch.stderr.strip()}")

        # 2. Check local working tree status
        res_status = run_git(["status", "--porcelain"])
        has_local_changes = bool(res_status.stdout.strip())

        committed = False
        # 3. Commit local changes first so pull --rebase never fails due to dirty working tree
        if has_local_changes:
            run_git(["add", "-A"])
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msg = f"{commit_prefix}: {now_str}"
            res_commit = run_git(["commit", "-m", msg])
            if res_commit.returncode == 0:
                committed = True
                if logger:
                    logger.info(f"git_sync ({repo_name}): committed: {msg}")

        # 4. Pull rebase to incorporate remote changes
        pull_succeeded = True
        res_pull = run_git(["pull", "--rebase", remote, branch])
        if res_pull.returncode != 0:
            pull_succeeded = False
            # If rebase encountered a conflict, abort rebase to avoid a wedged repository
            run_git(["rebase", "--abort"])
            if logger:
                logger.warning(f"git_sync ({repo_name}): rebase conflict or pull failure: {res_pull.stderr.strip()}")

        # 5. Push if rebase succeeded and local branch is ahead of remote
        if pull_succeeded:
            res_ahead = run_git(["rev-list", f"{remote}/{branch}..HEAD", "--count"])
            commits_ahead = 0
            if res_ahead.returncode == 0:
                try:
                    commits_ahead = int(res_ahead.stdout.strip())
                except ValueError:
                    commits_ahead = 0

            if commits_ahead > 0:
                res_push = run_git(["push", remote, branch])
                if res_push.returncode == 0:
                    if logger:
                        logger.info(f"git_sync ({repo_name}): pushed {commits_ahead} commit(s) to {remote}/{branch}")
                    return 1
                else:
                    if logger:
                        logger.warning(f"git_sync ({repo_name}): push failed: {res_push.stderr.strip()}")
                    return 0

        return 1 if committed else 0

    except subprocess.TimeoutExpired:
        if logger:
            logger.warning(f"git_sync ({repo_name}): Git command timed out (network unreachable?)")
        return 0
    except Exception as e:
        if logger:
            logger.warning(f"git_sync ({repo_name}): Unexpected error: {e}")
        return 0

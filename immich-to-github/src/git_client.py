"""Git-based upload sink.

Replaces the GitHub Contents-API client (``github_client.py``) with a plain
``git push`` to any remote. Because it targets a *git remote* rather than
github.com specifically, the same code stages photos to the local Gitea server
now and to GitHub later — only the remote URL changes.

Credentials are supplied at runtime via the ``GIT_PUSH_TOKEN`` env var (read in
``config.py``) and are injected as an HTTP ``Authorization`` header, never baked
into the remote URL. This keeps the token out of ``git remote -v`` and, more
importantly, out of git's error messages (which echo the remote URL on failure).
"""

import base64
import shutil
import subprocess
from pathlib import Path
from typing import List

from rich.console import Console

console = Console()


class GitClient:
    """Uploads files to a git remote via a local working clone."""

    def __init__(
        self,
        token: str,
        remote_host: str,
        remote_path: str,
        branch: str = "main",
        work_dir: str = "/data/repo",
        author_name: str = "immich-sync",
        author_email: str = "immich-sync@grnch.xyz",
        username: str = "oauth2",
        use_https: bool = False,
    ):
        """Initialize the git client.

        Args:
            token: Access token for the remote (from GIT_PUSH_TOKEN env var).
            remote_host: Host[:port] of the git remote, e.g. "grnchnas:30008".
            remote_path: Repo path on the remote, e.g. "grinchdubs/grnch.xyz_photos.git".
            branch: Branch to push to.
            work_dir: Local path for the working clone (persist on a volume).
            author_name: Git commit author name.
            author_email: Git commit author email.
            username: Basic-auth username paired with the token. Gitea accepts a
                valid token as the password regardless of username, so the
                default "oauth2" works; override via config if needed.
            use_https: Use https:// instead of http:// for the remote.
        """
        scheme = "https" if use_https else "http"
        # Clean URL — no credentials embedded, so git never logs the token.
        self.remote_url = f"{scheme}://{remote_host}/{remote_path.lstrip('/')}"
        self.branch = branch
        self.work_dir = Path(work_dir)
        self.author_name = author_name
        self.author_email = author_email

        # Precompute the Authorization header value (Basic base64("user:token")).
        raw = f"{username}:{token}".encode("utf-8")
        self._auth_header = "Authorization: Basic " + base64.b64encode(raw).decode("ascii")

        self._ensure_repo()

    # ------------------------------------------------------------------ #
    # Low-level git runners
    # ------------------------------------------------------------------ #
    def _git(self, *args: str, auth: bool = False, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command in the working clone.

        Args:
            *args: git arguments (without the leading "git").
            auth: If True, inject the Authorization header (for network ops).
            check: Raise on non-zero exit.
        """
        cmd: List[str] = ["git", "-C", str(self.work_dir)]
        if auth:
            # -c http.extraHeader keeps the token out of the URL and out of
            # any error output git prints.
            cmd += ["-c", f"http.extraHeader={self._auth_header}"]
        cmd += list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            # Surface git's stderr so daemon logs are debuggable. Safe to log:
            # the token lives in the extraHeader (redacted below), never in the
            # URL, so git's stderr can only contain the credential-free remote.
            safe_cmd = [
                "http.extraHeader=<redacted>" if a.startswith("http.extraHeader=") else a
                for a in cmd
            ]
            raise RuntimeError(
                f"git failed (rc={result.returncode}): {' '.join(safe_cmd)}\n"
                f"{result.stderr.strip()}"
            )
        return result

    def _remote_branch_exists(self) -> bool:
        """Return True if ``branch`` exists on the remote."""
        result = self._git(
            "ls-remote", "--heads", self.remote_url, self.branch,
            auth=True, check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def _ensure_repo(self) -> None:
        """Ensure the working clone exists and matches the remote branch.

        Handles a freshly-created (empty) remote repo with no commits yet.
        Runs every sync cycle, so it also resyncs the clone to the remote
        (discarding any local state left over from a failed push).
        """
        if not (self.work_dir / ".git").is_dir():
            self.work_dir.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q", check=True)
            self._git("remote", "add", "origin", self.remote_url, check=True)

        self._git("config", "user.name", self.author_name)
        self._git("config", "user.email", self.author_email)

        if self._remote_branch_exists():
            # Fetch and hard-reset onto the remote branch.
            self._git("fetch", "-q", "origin", self.branch, auth=True)
            self._git("checkout", "-q", "-B", self.branch, "FETCH_HEAD")
            self._git("reset", "-q", "--hard", "FETCH_HEAD")
        else:
            # Empty/new remote — start a fresh branch we'll push later.
            self._git("checkout", "-q", "-B", self.branch)

    # ------------------------------------------------------------------ #
    # Public surface (mirrors the old GitHubClient)
    # ------------------------------------------------------------------ #
    def upload_file(
        self,
        file_path: Path,
        github_path: str,
        commit_message: str,
        overwrite: bool = False,
    ) -> str:
        """Stage a file into the working clone (no commit/push yet).

        Committing and pushing is deferred to ``commit_and_push`` so a whole
        sync cycle becomes a single push instead of one per photo. The
        ``commit_message`` arg is accepted for interface compatibility but is
        not used per-file.

        Args:
            file_path: Local path to the downloaded file.
            github_path: Destination path within the repo (kept name for
                interface compatibility with the old sink).
            commit_message: Unused per-file (see above).
            overwrite: Allow replacing an existing file at that path.

        Returns:
            A raw URL to the file on the remote.
        """
        dest = self.work_dir / github_path
        if dest.exists() and not overwrite:
            raise FileExistsError(
                f"File {github_path} already exists. Use force to overwrite."
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)
        self._git("add", "--", github_path)
        console.print(f"[green]Staged:[/green] {github_path}")
        return self.get_raw_url(github_path)

    def commit_and_push(self, commit_message: str) -> bool:
        """Commit staged changes (if any) and push to the remote.

        Returns:
            True if a push happened, False if there was nothing to commit.

        Raises:
            subprocess.CalledProcessError: If the push fails (caller should
            NOT persist sync state in that case, so it retries next cycle).
        """
        # Nothing staged → nothing to do.
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return False

        self._git("commit", "-q", "-m", commit_message)
        # HEAD:branch also creates the branch on an empty remote.
        self._git("push", "-q", "origin", f"HEAD:{self.branch}", auth=True)
        console.print(f"[green]Pushed to[/green] {self.remote_url} ({self.branch})")
        return True

    def test_connection(self) -> bool:
        """Check the remote is reachable and the token authenticates."""
        try:
            result = self._git(
                "ls-remote", self.remote_url, auth=True, check=False,
            )
            if result.returncode == 0:
                return True
            console.print(
                f"[red]Git connection test failed (rc={result.returncode})[/red]"
            )
            return False
        except Exception as e:
            console.print(f"[red]Git connection test failed: {e}[/red]")
            return False

    def get_raw_url(self, github_path: str) -> str:
        """Return a raw file URL on the remote (best-effort, for state records)."""
        base = self.remote_url[:-4] if self.remote_url.endswith(".git") else self.remote_url
        return f"{base}/raw/branch/{self.branch}/{github_path}"

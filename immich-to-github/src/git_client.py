"""Git-based upload sink.

Replaces the GitHub Contents-API client (``github_client.py``) with a plain
``git push`` to any remote. Because it targets a *git remote* rather than
github.com specifically, the same code stages photos to the local Gitea server
now and to GitHub later — only the remote URL changes.

Credentials are supplied at runtime via the ``GIT_PUSH_TOKEN`` env var (read in
``config.py``) and are injected as an HTTP ``Authorization`` header, never baked
into the remote URL. This keeps the token out of ``git remote -v`` and, more
importantly, out of git's error messages (which echo the remote URL on failure).

Design notes:

* **Push-only.** This tool is the *sole writer* of the target repo, so it never
  needs to ``fetch`` in steady state — it keeps a persistent working clone and
  just appends commits. Avoiding per-cycle fetches also sidesteps environments
  where ``git-upload-pack`` (fetch) is unreliable but ``git-receive-pack``
  (push) is fine (e.g. an MTU-limited tunnel). A one-time ``fetch`` is only used
  to *bootstrap* a fresh clone against an already-populated remote.
* **Failed-push safety.** After each successful push we move a local marker ref
  (``refs/immich/last-pushed``) to HEAD. On the next cycle we hard-reset the
  clone back to that marker, discarding any commit/files left behind by a failed
  push so the retry starts clean. No network needed.
* **No infinite hangs.** Every git invocation has a timeout; a stuck network op
  raises instead of freezing the daemon forever, so the cycle fails and retries.
"""

import base64
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from rich.console import Console

console = Console()

# Local ref tracking the last commit we successfully pushed. Used to reset the
# working clone to a known-good state on the cycle after a failed push.
_MARKER_REF = "refs/immich/last-pushed"


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
        net_timeout: int = 120,
        local_timeout: int = 60,
    ):
        """Initialize the git client.

        Args:
            token: Access token for the remote (from GIT_PUSH_TOKEN env var).
            remote_host: Host[:port] of the git remote, e.g. "grnchnas:30008".
            remote_path: Repo path on the remote, e.g. "grnch/grnch.xyz_photos.git".
            branch: Branch to push to.
            work_dir: Local path for the working clone (persist on a volume).
            author_name: Git commit author name.
            author_email: Git commit author email.
            username: Basic-auth username paired with the token. Gitea accepts a
                valid token as the password regardless of username, so the
                default "oauth2" works; override via config if needed.
            use_https: Use https:// instead of http:// for the remote.
            net_timeout: Seconds before a network git op (fetch/push/ls-remote)
                is aborted, so a stuck connection never wedges the daemon.
            local_timeout: Seconds before a local git op is aborted.
        """
        scheme = "https" if use_https else "http"
        # Clean URL — no credentials embedded, so git never logs the token.
        self.remote_url = f"{scheme}://{remote_host}/{remote_path.lstrip('/')}"
        self.branch = branch
        self.work_dir = Path(work_dir)
        self.author_name = author_name
        self.author_email = author_email
        self.net_timeout = net_timeout
        self.local_timeout = local_timeout

        # Precompute the Authorization header value (Basic base64("user:token")).
        raw = f"{username}:{token}".encode("utf-8")
        self._auth_header = "Authorization: Basic " + base64.b64encode(raw).decode("ascii")

        # Set True on a fresh bootstrap so the first push force-overwrites any
        # unrelated remote history (see _ensure_repo). Cleared after first push.
        self._force_next_push = False

        self._ensure_repo()

    # ------------------------------------------------------------------ #
    # Low-level git runners
    # ------------------------------------------------------------------ #
    def _git(
        self,
        *args: str,
        auth: bool = False,
        check: bool = True,
        timeout: Optional[int] = None,
    ) -> subprocess.CompletedProcess:
        """Run a git command in the working clone.

        Args:
            *args: git arguments (without the leading "git").
            auth: If True, inject the Authorization header (for network ops).
            check: Raise on non-zero exit.
            timeout: Seconds before aborting. Defaults to local_timeout; pass
                net_timeout for network ops.
        """
        if timeout is None:
            timeout = self.local_timeout
        cmd: List[str] = ["git", "-C", str(self.work_dir)]
        if auth:
            # -c http.extraHeader keeps the token out of the URL and out of
            # any error output git prints.
            cmd += ["-c", f"http.extraHeader={self._auth_header}"]
        cmd += list(args)
        # GIT_TERMINAL_PROMPT=0 ensures git fails fast instead of blocking on an
        # interactive credential prompt if auth is ever rejected.
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        # Redacted form for any error message (never expose the token).
        safe_cmd = [
            "http.extraHeader=<redacted>" if a.startswith("http.extraHeader=") else a
            for a in cmd
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, env=env
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"git timed out after {timeout}s: {' '.join(safe_cmd)}"
            )
        if check and result.returncode != 0:
            # Surface git's stderr so daemon logs are debuggable. Safe to log:
            # the token lives in the extraHeader (redacted above), never in the
            # URL, so git's stderr can only contain the credential-free remote.
            raise RuntimeError(
                f"git failed (rc={result.returncode}): {' '.join(safe_cmd)}\n"
                f"{result.stderr.strip()}"
            )
        return result

    def _local_ref_exists(self, ref: str) -> bool:
        """Return True if a ref (branch/marker) exists in the local clone."""
        return self._git(
            "rev-parse", "--verify", "--quiet", ref, check=False
        ).returncode == 0

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def _ensure_repo(self) -> None:
        """Ensure the working clone exists and is at a clean, known-good state.

        Runs every sync cycle and does NO network I/O — never fetches. In steady
        state it resets the persistent clone to the last successfully-pushed
        commit (discarding anything a failed push left behind). On a brand-new
        clone it starts a fresh branch and arms a one-time force-push, because
        ``git-upload-pack`` (fetch/clone) is unreliable on this remote while
        ``git-receive-pack`` (push) works, and the repo content is fully
        re-derivable from Immich anyway.
        """
        if not (self.work_dir / ".git").is_dir():
            self.work_dir.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q")
            self._git("remote", "add", "origin", self.remote_url)

        self._git("config", "user.name", self.author_name)
        self._git("config", "user.email", self.author_email)

        if self._local_ref_exists(f"refs/heads/{self.branch}"):
            # Persistent clone / steady state — sole writer, no fetch needed.
            self._git("checkout", "-q", self.branch)
            if self._local_ref_exists(_MARKER_REF):
                # Discard any commit/files left by a failed previous push so the
                # retry starts from the last state we actually pushed.
                self._git("reset", "-q", "--hard", _MARKER_REF)
            return

        # No local branch yet → bootstrap WITHOUT fetching. Start a fresh branch
        # with an empty baseline commit (so there is always a marker to reset to
        # on a failed-push retry). The first push force-overwrites whatever
        # unrelated history the remote may hold; from then on pushes are normal
        # fast-forwards on top of our own history.
        self._git("checkout", "-q", "-B", self.branch)
        self._git("commit", "-q", "--allow-empty", "-m",
                  "Initialize photos repository")
        self._git("update-ref", _MARKER_REF, "HEAD")
        self._force_next_push = True

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

        On a successful push the ``last-pushed`` marker is advanced to HEAD so a
        later failed cycle can be rolled back to this point.

        Returns:
            True if a push happened, False if there was nothing to commit.

        Raises:
            RuntimeError: If the push fails or times out (caller should NOT
            persist sync state in that case, so it retries next cycle).
        """
        # Nothing staged → nothing to do.
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return False

        self._git("commit", "-q", "-m", commit_message)
        # First push after a fresh bootstrap force-overwrites any unrelated
        # remote history; subsequent pushes are normal fast-forwards.
        push_args = ["push", "-q"]
        if self._force_next_push:
            push_args.append("--force")
        # HEAD:branch also creates the branch on an empty remote.
        push_args += ["origin", f"HEAD:{self.branch}"]
        self._git(*push_args, auth=True, timeout=self.net_timeout)
        self._force_next_push = False
        # Record this as the last known-good pushed state.
        self._git("update-ref", _MARKER_REF, "HEAD")
        console.print(f"[green]Pushed to[/green] {self.remote_url} ({self.branch})")
        return True

    def test_connection(self) -> bool:
        """Check the remote is reachable and the token authenticates."""
        try:
            result = self._git(
                "ls-remote", self.remote_url, auth=True, check=False,
                timeout=self.net_timeout,
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

"""Git-based upload sink for the reconcile engine.

The sync engine treats the Immich album as the source of truth and reconciles
the photos repo to match it every run (add / delete / rename). This client is
the thin git layer under that: it exposes the working clone as a plain
directory the engine manipulates (download, rename, delete, write manifest),
then stages and pushes whatever changed.

Design notes:

* **Push-only.** This tool is the *sole writer* of the target repo, so it never
  needs to ``fetch`` — it keeps a persistent working clone and appends commits.
  Avoiding fetch also sidesteps environments where ``git-upload-pack`` (fetch)
  is unreliable but ``git-receive-pack`` (push) is fine (e.g. an MTU-limited
  tunnel). A fresh clone bootstraps by starting an empty branch and
  force-pushing once, since the content is fully re-derivable from Immich.
* **No incremental state.** Correctness comes from reconcile, not from a
  side-car state file. The working tree is the actual state; the album is the
  desired state; the diff between them is the commit.
* **Unpushed-commit safety.** After each successful push we move a marker ref
  (``refs/immich/last-pushed``) to HEAD. If a push fails, the commit stays and
  the next cycle notices HEAD has moved past the marker and re-pushes it — no
  network state to reconcile, no rollback needed.
* **No infinite hangs.** Every git invocation has a timeout.

Credentials come from ``GIT_PUSH_TOKEN`` (read in ``config.py``) and are
injected as an HTTP ``Authorization`` header, never baked into the remote URL,
so the token stays out of ``git remote -v`` and out of git's error output.
"""

import base64
import os
import subprocess
from pathlib import Path
from typing import List, Optional

from rich.console import Console

console = Console()

# Local ref tracking the last commit we successfully pushed. Used to detect a
# commit left unpushed by a failed push so the next cycle re-pushes it.
_MARKER_REF = "refs/immich/last-pushed"


class GitClient:
    """Exposes a git working clone as a reconcilable directory + push."""

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
            net_timeout: Seconds before a network git op (push/ls-remote) is
                aborted, so a stuck connection never wedges the daemon.
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
            # Safe to log: the token lives in the extraHeader (redacted above),
            # never in the URL, so git's stderr only holds the clean remote.
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

    def _rev(self, ref: str) -> str:
        """Return the commit SHA a ref points at."""
        return self._git("rev-parse", ref).stdout.strip()

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def _ensure_repo(self) -> None:
        """Ensure the working clone exists and the target branch is checked out.

        Does NO network I/O — never fetches. On an existing clone it just checks
        out the branch (the reconcile pass recomputes the full desired tree, so
        any leftover from a crashed cycle is corrected by the next commit). On a
        brand-new clone it starts a fresh branch with an empty baseline commit
        and arms a one-time force-push, because ``git-upload-pack`` (clone) is
        unreliable on this remote and the content is re-derivable from Immich.
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
            return

        # No local branch yet → bootstrap WITHOUT fetching. Start a fresh branch
        # with an empty baseline commit (so there is always a marker to build
        # on). The first push force-overwrites whatever unrelated history the
        # remote may hold; from then on pushes are normal fast-forwards.
        self._git("checkout", "-q", "-B", self.branch)
        self._git("commit", "-q", "--allow-empty", "-m",
                  "Initialize photos repository")
        self._git("update-ref", _MARKER_REF, "HEAD")
        self._force_next_push = True

    # ------------------------------------------------------------------ #
    # Reconcile primitives (the engine manipulates the working tree directly)
    # ------------------------------------------------------------------ #
    def work_path(self, rel_path: str) -> Path:
        """Absolute path inside the working clone for a repo-relative path."""
        return self.work_dir / rel_path

    def list_files(self, folder: str) -> List[str]:
        """Return the names of files directly under ``folder`` (no subdirs).

        Empty list if the folder does not exist yet.
        """
        p = self.work_dir / folder
        if not p.is_dir():
            return []
        return [f.name for f in p.iterdir() if f.is_file()]

    def read_text(self, rel_path: str) -> Optional[str]:
        """Return the text contents of a repo file, or None if it is absent."""
        p = self.work_dir / rel_path
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8")

    def stage(self, folder: str) -> None:
        """Stage every change (adds, deletes, renames) under ``folder``."""
        self._git("add", "-A", "--", folder)

    # ------------------------------------------------------------------ #
    # Commit + push
    # ------------------------------------------------------------------ #
    def commit_and_push(self, commit_message: str) -> bool:
        """Commit staged changes (if any) and push if there is anything unpushed.

        Pushes when either new changes were just committed OR a previous cycle
        left a commit unpushed (HEAD is ahead of the last-pushed marker). On a
        successful push the marker advances to HEAD.

        Returns:
            True if a push happened, False if the remote was already up to date.

        Raises:
            RuntimeError: If the push fails or times out. The commit stays local
            and the next cycle retries the push; no state needs unwinding.
        """
        staged = self._git("diff", "--cached", "--quiet", check=False).returncode != 0
        if staged:
            self._git("commit", "-q", "-m", commit_message)

        head = self._rev("HEAD")
        marker = self._rev(_MARKER_REF) if self._local_ref_exists(_MARKER_REF) else None
        if not staged and marker == head:
            return False  # nothing new and nothing left unpushed

        self._push(force=self._force_next_push)
        self._force_next_push = False
        self._git("update-ref", _MARKER_REF, "HEAD")
        console.print(f"[green]Pushed to[/green] {self.remote_url} ({self.branch})")
        return True

    def _push(self, force: bool) -> None:
        """Push HEAD to the remote branch, force-retrying on non-fast-forward.

        We never fetch (upload-pack is unreliable here) so the local clone can
        diverge from the remote — e.g. a stale /data from an earlier run, or
        unrelated history the remote already held. Since the daemon is the sole
        writer and the content is fully re-derivable from Immich, a
        non-fast-forward rejection is resolved by force-overwriting rather than
        aborting forever.
        """
        push_args = ["push", "-q"]
        if force:
            push_args.append("--force")
        # HEAD:branch also creates the branch on an empty remote.
        push_args += ["origin", f"HEAD:{self.branch}"]
        try:
            self._git(*push_args, auth=True, timeout=self.net_timeout)
        except RuntimeError as e:
            msg = str(e).lower()
            is_non_ff = (
                "fetch first" in msg
                or "non-fast-forward" in msg
                or "rejected" in msg
                or "behind" in msg
            )
            if force or not is_non_ff:
                raise
            console.print(
                "[yellow]Push rejected (remote diverged); force-overwriting "
                "(sole writer, content re-derivable from Immich)[/yellow]"
            )
            self._push(force=True)

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
        """Return a raw file URL on the remote (best-effort)."""
        base = self.remote_url[:-4] if self.remote_url.endswith(".git") else self.remote_url
        return f"{base}/raw/branch/{self.branch}/{github_path}"

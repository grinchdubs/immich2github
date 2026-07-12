"""Reconcile engine: make the photos repo match the Immich album.

The Immich album is the source of truth. Every run computes the album's full
desired state (which assets, in what order, with what caption) and reconciles
the repo to match it: download new assets, delete ones removed from the album,
and rename on reorder. Running it twice with no album change is a fast no-op,
so deletions, reorders, and caption edits "just work" and there is no
incremental sync state to corrupt.

Ordering: files are named ``NNN_originalname.ext`` where ``NNN`` is the
zero-padded album position (from ``fileCreatedAt`` per the album's ``order``).
Reorders therefore surface as renames in the git diff.

Manifest: each folder gets an ``index.json`` capturing the ordered list of
``{position, file, immich_id, checksum, caption}``. It drives the site gallery
(order + captions) and its ``checksum`` doubles as a cache so an unchanged asset
skips a local checksum re-read. Captions are fetched per-asset every run and
compared to the manifest, because Immich does not bump an asset's ``updatedAt``
on a description edit (so there is no cheap change signal to cache against).
"""

import base64
import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console

from .config import Config
from .immich_client import ImmichClient, ImmichAsset
from .git_client import GitClient

console = Console()

MANIFEST_NAME = "index.json"
POS_WIDTH = 3
_POS_RE = re.compile(r"^\d{%d}_" % POS_WIDTH)


def _strip_pos(name: str) -> str:
    """Drop a leading ``NNN_`` position prefix to recover the original name."""
    return _POS_RE.sub("", name)


def _local_checksum(path: Path) -> str:
    """Compute Immich's checksum (base64 of the file's SHA-1) for a local file."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode("ascii")


class SyncEngine:
    """Reconciles an Immich album into the photos git repo."""

    def __init__(self, config: Config, dry_run: bool = False):
        """Initialize sync engine.

        Args:
            config: Configuration object.
            dry_run: If True, report the plan without changing or pushing.
        """
        self.config = config
        self.dry_run = dry_run

        self.immich_client = ImmichClient(
            config.immich.api_url, config.immich.api_key
        )
        self.sink = GitClient(
            token=config.git_token,
            remote_host=config.git_remote_host,
            remote_path=config.git_remote_path,
            branch=config.git_branch,
            work_dir=config.git_work_dir,
            author_name=config.git_author_name,
            author_email=config.git_author_email,
            username=config.git_username,
            use_https=config.git_use_https,
        )

    async def test_connections(self) -> bool:
        """Test connections to Immich and the git remote."""
        console.print("[bold]Testing connections...[/bold]")

        immich_ok = await self.immich_client.test_connection()
        git_ok = self.sink.test_connection()

        if immich_ok:
            console.print("[green]✓ Immich connection successful[/green]")
        else:
            console.print("[red]✗ Immich connection failed[/red]")

        if git_ok:
            console.print(
                f"[green]✓ Git remote '{self.config.git_remote_display}' reachable[/green]"
            )
        else:
            console.print("[red]✗ Git remote connection failed[/red]")

        return immich_ok and git_ok

    # ------------------------------------------------------------------ #
    # Desired state
    # ------------------------------------------------------------------ #
    def _included_ordered(
        self, assets: List[ImmichAsset], excluded_ids: set, order: str
    ) -> List[ImmichAsset]:
        """Filter to syncable assets and sort them into album order."""
        included = []
        for a in assets:
            ext = Path(a.original_filename).suffix.lower()
            if ext not in self.config.allowed_extensions:
                continue
            if a.id in excluded_ids or any(
                tag in self.config.exclude_tags for tag in a.tags
            ):
                continue
            included.append(a)
        # Album order is date-based (see NOTES.md); "desc" = newest first.
        included.sort(
            key=lambda a: (a.file_created_at or ""),
            reverse=(str(order).lower() != "asc"),
        )
        return included

    def _load_manifest(self, folder: str) -> Dict[str, dict]:
        """Return the previous manifest indexed by immich_id (empty if none)."""
        raw = self.sink.read_text(f"{folder}/{MANIFEST_NAME}")
        if not raw:
            return {}
        try:
            return {
                p["immich_id"]: p
                for p in json.loads(raw).get("photos", [])
                if "immich_id" in p
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            console.print("[yellow]Manifest unreadable; rebuilding from scratch[/yellow]")
            return {}

    async def _build_plan(
        self, album_name: str, folder: str, force: bool
    ) -> Optional[dict]:
        """Compute the reconcile plan for one album.

        Returns a dict describing the album, the per-asset actions, and the
        files to delete — or None if the album is missing from Immich.
        """
        albums = await self.immich_client.get_albums()
        album = next((a for a in albums if a.get("albumName") == album_name), None)
        if not album:
            return None

        order = album.get("order", "desc")
        assets = await self.immich_client.get_album_assets(album["id"])
        excluded_ids = await self.immich_client.get_album_excluded_asset_ids(
            album["id"], self.config.exclude_tags
        )
        included = self._included_ordered(assets, excluded_ids, order)

        by_id = self._load_manifest(folder)
        actual_files = [f for f in self.sink.list_files(folder) if f != MANIFEST_NAME]
        # Map existing files by their original name (position prefix stripped)
        # so the first reconcile after the append era matches content without
        # re-downloading, and so reorders reuse the same bytes.
        by_orig: Dict[str, List[str]] = defaultdict(list)
        for f in actual_files:
            by_orig[_strip_pos(f)].append(f)

        consumed: set = set()
        items: List[dict] = []
        for pos, a in enumerate(included, start=1):
            target = f"{pos:0{POS_WIDTH}d}_{os.path.basename(a.original_filename)}"
            om = by_id.get(a.id)

            # Locate the current file holding this asset, if any.
            cur = None
            if om and om.get("file") in actual_files and om["file"] not in consumed:
                cur = om["file"]
            else:
                cands = [
                    f for f in by_orig.get(os.path.basename(a.original_filename), [])
                    if f not in consumed
                ]
                cur = cands[0] if cands else None

            content_ok = False
            if cur:
                consumed.add(cur)
                if force:
                    content_ok = False
                elif om and om.get("file") == cur and om.get("checksum") is not None:
                    content_ok = om["checksum"] == a.checksum
                else:
                    content_ok = (
                        _local_checksum(self.sink.work_path(f"{folder}/{cur}"))
                        == a.checksum
                    )

            # Caption must be fetched per-asset every run: Immich does NOT bump
            # an asset's updatedAt when its description changes, and the bulk
            # search API omits descriptions entirely — so there is no cheap
            # change signal to cache against. Compare to the manifest to detect
            # edits.
            caption = await self.immich_client.get_asset_description(a.id)
            cap_changed = bool(om) and om.get("caption") != caption

            if cur and content_ok:
                action = "keep" if cur == target else "rename"
            elif cur and not content_ok:
                action = "update"
            else:
                action = "add"

            items.append({
                "asset": a,
                "target": target,
                "position": pos,
                "cur": cur,
                "action": action,
                "caption": caption,
                "cap_changed": cap_changed,
            })

        to_delete = [f for f in actual_files if f not in consumed]
        return {
            "album_name": album_name,
            "folder": folder,
            "order": order,
            "total": len(assets),
            "items": items,
            "to_delete": to_delete,
        }

    # ------------------------------------------------------------------ #
    # Apply
    # ------------------------------------------------------------------ #
    async def _apply_plan(self, plan: dict) -> dict:
        """Execute a reconcile plan: move/download/delete, write manifest, push."""
        folder = plan["folder"]
        items = plan["items"]
        folder_path = self.sink.work_path(folder)
        folder_path.mkdir(parents=True, exist_ok=True)

        # Clear any staging leftovers from a crashed previous cycle.
        for f in self.sink.list_files(folder):
            if f.startswith(".stage_"):
                os.remove(folder_path / f)

        def stage_name(asset_id: str) -> Path:
            return folder_path / f".stage_{asset_id}"

        # Phase 1 — gather each asset's bytes under a unique staging name keyed
        # by immich_id. Keyed staging avoids rename collisions when positions
        # shuffle (two assets swapping filenames).
        for it in items:
            a = it["asset"]
            dest = stage_name(a.id)
            if it["action"] in ("keep", "rename"):
                os.replace(folder_path / it["cur"], dest)
            else:  # add / update
                if it["cur"]:  # content changed under an existing name
                    old = folder_path / it["cur"]
                    if old.exists():
                        os.remove(old)
                await self.immich_client.download_asset(
                    a.id, folder_path, filename=f".stage_{a.id}"
                )

        # Delete assets no longer in the album.
        for f in plan["to_delete"]:
            p = folder_path / f
            if p.exists():
                os.remove(p)

        # Phase 2 — move staging files to their final ordered names.
        for it in items:
            os.replace(stage_name(it["asset"].id), folder_path / it["target"])

        # Build the manifest (order + captions; checksum doubles as a cache so
        # unchanged assets skip a local re-read next run).
        core = {
            "album": plan["album_name"],
            "order": plan["order"],
            "count": len(items),
            "photos": [
                {
                    "position": it["position"],
                    "file": it["target"],
                    "immich_id": it["asset"].id,
                    "checksum": it["asset"].checksum,
                    "caption": it["caption"],
                }
                for it in items
            ],
        }

        # Keep generated_at stable when the desired state is unchanged so a
        # no-op run produces byte-identical JSON — otherwise a fresh timestamp
        # every cycle would stage a change and push an empty commit forever.
        generated_at = datetime.now(timezone.utc).isoformat()
        prev_raw = self.sink.read_text(f"{folder}/{MANIFEST_NAME}")
        if prev_raw:
            try:
                prev = json.loads(prev_raw)
                if all(prev.get(k) == core[k] for k in core):
                    generated_at = prev.get("generated_at", generated_at)
            except json.JSONDecodeError:
                pass

        manifest = {"generated_at": generated_at, **core}
        (folder_path / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        self.sink.stage(folder)
        pushed = self.sink.commit_and_push(_commit_message(plan))
        return {"pushed": pushed}

    # ------------------------------------------------------------------ #
    # Public surface
    # ------------------------------------------------------------------ #
    async def sync_album(self, album_name: str, force: bool = False) -> dict:
        """Reconcile a single album; returns a stats dict."""
        folder = self.config.album_mappings.get(album_name, album_name)
        console.print(f"\n[bold cyan]Reconciling album: {album_name}[/bold cyan]")
        console.print(f"[dim]Target folder: {folder}[/dim]")

        plan = await self._build_plan(album_name, folder, force)
        if plan is None:
            console.print(f"[red]Album '{album_name}' not found in Immich[/red]")
            return _result(album_name, error="Album not found")

        counts = _count_actions(plan)
        console.print(
            f"[dim]{plan['total']} in album → "
            f"+{counts['added']} added, -{counts['removed']} removed, "
            f"~{counts['renamed']} reordered, {counts['updated']} updated, "
            f"{counts['recaptioned']} recaptioned[/dim]"
        )

        if self.dry_run:
            for it in plan["items"]:
                if it["action"] != "keep" or it["cap_changed"]:
                    console.print(
                        f"  • [{it['action']}] {it['asset'].original_filename} "
                        f"→ {it['target']}"
                    )
            for f in plan["to_delete"]:
                console.print(f"  • [delete] {f}")
            return _result(album_name, total=plan["total"], **counts, dry_run=True)

        try:
            applied = await self._apply_plan(plan)
        except Exception as e:
            console.print(f"[red]Reconcile push failed (will retry next cycle): {e}[/red]")
            return _result(album_name, total=plan["total"], failed=1, error=str(e))

        if applied["pushed"]:
            console.print(f"[green]Pushed changes for '{album_name}'[/green]")
        else:
            console.print(f"[green]'{album_name}' already up to date[/green]")

        return _result(album_name, total=plan["total"], pushed=applied["pushed"], **counts)

    async def sync_all_albums(self, force: bool = False) -> List[dict]:
        """Reconcile every configured album."""
        results = []
        for album_name in self.config.album_mappings.keys():
            results.append(await self.sync_album(album_name, force=force))
        return results

    async def sync_tag(self, tag: str, force: bool = False) -> dict:
        """Deprecated: tag-based sync is not supported in the reconcile model.

        The album is the single source of truth; use exclude_tags to remove
        assets. Kept as a no-op stub so existing callers don't break.
        """
        console.print(
            f"[yellow]Tag sync is deprecated in reconcile mode; ignoring '{tag}'. "
            f"Curate the album instead.[/yellow]"
        )
        return _result(tag, is_tag=True)

    async def sync_all_tags(self, force: bool = False) -> List[dict]:
        """Deprecated: see sync_tag."""
        return [await self.sync_tag(t, force=force) for t in self.config.tag_mappings]

    async def close(self) -> None:
        """Close all clients."""
        await self.immich_client.close()


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def _count_actions(plan: dict) -> dict:
    items = plan["items"]
    return {
        "added": sum(1 for it in items if it["action"] == "add"),
        "updated": sum(1 for it in items if it["action"] == "update"),
        "renamed": sum(1 for it in items if it["action"] == "rename"),
        "recaptioned": sum(1 for it in items if it["cap_changed"]),
        "removed": len(plan["to_delete"]),
    }


def _commit_message(plan: dict) -> str:
    c = _count_actions(plan)
    parts = []
    if c["added"]:
        parts.append(f"{c['added']} added")
    if c["removed"]:
        parts.append(f"{c['removed']} removed")
    if c["renamed"]:
        parts.append(f"{c['renamed']} reordered")
    if c["updated"]:
        parts.append(f"{c['updated']} updated")
    if c["recaptioned"]:
        parts.append(f"{c['recaptioned']} recaptioned")
    summary = ", ".join(parts) if parts else "no changes"
    return f"Reconcile album '{plan['album_name']}': {summary}"


def _result(name: str, is_tag: bool = False, **kw) -> dict:
    """Build a uniform result dict with all count keys present."""
    key = "tag" if is_tag else "album"
    out = {
        key: name,
        "total": kw.get("total", 0),
        "added": kw.get("added", 0),
        "updated": kw.get("updated", 0),
        "renamed": kw.get("renamed", 0),
        "recaptioned": kw.get("recaptioned", 0),
        "removed": kw.get("removed", 0),
        "failed": kw.get("failed", 0),
        "pushed": kw.get("pushed", False),
    }
    if "dry_run" in kw:
        out["dry_run"] = kw["dry_run"]
    if "error" in kw:
        out["error"] = kw["error"]
    return out

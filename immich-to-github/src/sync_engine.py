"""Core sync engine that orchestrates Immich to GitHub synchronization."""

import asyncio
from pathlib import Path
from typing import List, Optional, Set
import tempfile

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from .config import Config
from .immich_client import ImmichClient, ImmichAsset
from .git_client import GitClient
from .state_manager import SyncState

console = Console()


class SyncEngine:
    """Orchestrates synchronization between Immich and GitHub."""

    def __init__(self, config: Config, dry_run: bool = False):
        """Initialize sync engine.

        Args:
            config: Configuration object
            dry_run: If True, only show what would be synced without uploading
        """
        self.config = config
        self.dry_run = dry_run

        # Initialize clients
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
        self.state = SyncState(
            config.state_file_path, config.state_backup_enabled
        )

    async def test_connections(self) -> bool:
        """Test connections to Immich and GitHub.

        Returns:
            True if both connections are successful, False otherwise
        """
        console.print("[bold]Testing connections...[/bold]")

        immich_ok = await self.immich_client.test_connection()
        git_ok = self.sink.test_connection()

        if immich_ok:
            console.print("[green]✓ Immich connection successful[/green]")
        else:
            console.print("[red]✗ Immich connection failed[/red]")

        if git_ok:
            console.print(f"[green]✓ Git remote '{self.config.git_remote_display}' reachable[/green]")
        else:
            console.print("[red]✗ Git remote connection failed[/red]")

        return immich_ok and git_ok

    def _should_sync_asset(self, asset: ImmichAsset) -> bool:
        """Check if an asset should be synced.

        Args:
            asset: Immich asset to check

        Returns:
            True if asset should be synced, False otherwise
        """
        # Check if already synced
        if self.state.is_synced(asset.id):
            return False

        # Check file extension
        file_ext = Path(asset.original_filename).suffix.lower()
        if file_ext not in self.config.allowed_extensions:
            return False

        # Check excluded tags
        if any(tag in self.config.exclude_tags for tag in asset.tags):
            return False

        return True

    def _get_github_path(self, asset: ImmichAsset, tag: str) -> str:
        """Generate GitHub path for an asset.

        Args:
            asset: Immich asset
            tag: Tag being synced

        Returns:
            Path in GitHub repository
        """
        # Get folder from tag mapping
        folder = self.config.tag_mappings.get(tag, tag)

        # Apply filename pattern
        filename_pattern = self.config.filename_pattern
        filename = filename_pattern.format(
            original=asset.original_filename,
            tag=tag,
            date=asset.file_created_at[:10] if asset.file_created_at else "unknown",
            timestamp=asset.file_created_at.replace(":", "-") if asset.file_created_at else "unknown",
        )

        return f"{folder}/{filename}"

    async def sync_tag(
        self,
        tag: str,
        force: bool = False,
    ) -> dict:
        """Sync assets with a specific tag.

        Args:
            tag: Tag to sync
            force: If True, re-upload even if already synced

        Returns:
            Dictionary with sync results
        """
        console.print(f"\n[bold cyan]Syncing tag: {tag}[/bold cyan]")

        # Check if tag is mapped
        if tag not in self.config.tag_mappings:
            console.print(f"[yellow]Warning: Tag '{tag}' not in tag_mappings. Using tag name as folder.[/yellow]")

        # Fetch assets from Immich
        console.print(f"[dim]Fetching assets with tag '{tag}' from Immich...[/dim]")
        assets = await self.immich_client.get_assets_by_tag(tag)
        console.print(f"[dim]Found {len(assets)} assets with tag '{tag}'[/dim]")

        # Filter assets that need syncing
        if not force:
            assets_to_sync = [a for a in assets if self._should_sync_asset(a)]
            skipped = len(assets) - len(assets_to_sync)
            if skipped > 0:
                console.print(f"[dim]Skipping {skipped} already synced assets[/dim]")
        else:
            assets_to_sync = assets
            console.print("[yellow]Force mode: re-syncing all assets[/yellow]")

        if not assets_to_sync:
            console.print("[green]No new assets to sync![/green]")
            return {
                "tag": tag,
                "total": len(assets),
                "synced": 0,
                "skipped": len(assets),
                "failed": 0,
            }

        # Dry run mode
        if self.dry_run:
            console.print(f"\n[yellow]DRY RUN: Would sync {len(assets_to_sync)} assets:[/yellow]")
            for asset in assets_to_sync:
                github_path = self._get_github_path(asset, tag)
                console.print(f"  • {asset.original_filename} → {github_path}")
            return {
                "tag": tag,
                "total": len(assets),
                "synced": 0,
                "skipped": 0,
                "failed": 0,
                "dry_run": True,
            }

        # Sync assets
        synced = 0
        failed = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Syncing {len(assets_to_sync)} assets...",
                total=len(assets_to_sync),
            )

            for asset in assets_to_sync:
                try:
                    # Download asset to temp directory
                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_path = Path(temp_dir)
                        local_file = await self.immich_client.download_asset(
                            asset.id, temp_path, asset.original_filename
                        )

                        # Check file size
                        if self.config.max_file_size_mb:
                            size_mb = local_file.stat().st_size / (1024 * 1024)
                            if size_mb > self.config.max_file_size_mb:
                                console.print(
                                    f"[yellow]Skipping {asset.original_filename}: "
                                    f"size {size_mb:.1f}MB exceeds limit[/yellow]"
                                )
                                progress.advance(task)
                                continue

                        # Upload to GitHub
                        github_path = self._get_github_path(asset, tag)
                        commit_msg = self.config.commit_message_template.format(
                            tag=tag,
                            count=1,
                            date=asset.file_created_at[:10] if asset.file_created_at else "unknown",
                        )

                        url = self.sink.upload_file(
                            local_file,
                            github_path,
                            commit_msg,
                            overwrite=force,
                        )

                        # Mark as synced
                        self.state.mark_synced(
                            asset.id,
                            github_path,
                            checksum=asset.checksum,
                            url=url,
                        )
                        synced += 1

                except Exception as e:
                    console.print(f"[red]Failed to sync {asset.original_filename}: {e}[/red]")
                    failed += 1

                progress.advance(task)

        # Commit + push everything staged this cycle, then persist state.
        # Only save state if the push succeeded, so a failed push retries
        # next cycle instead of silently marking assets as synced.
        if synced > 0:
            try:
                self.sink.commit_and_push(f"Sync {synced} photo(s) from tag '{tag}'")
                self.state.save_state()
            except Exception as e:
                console.print(f"[red]Push failed, not saving state (will retry): {e}[/red]")
                # Drop in-memory marks for assets we never actually pushed so
                # they are retried next cycle instead of skipped as "synced".
                self.state.reload()
                failed += synced
                synced = 0

        # Summary
        console.print(f"\n[bold green]Sync completed for tag '{tag}':[/bold green]")
        console.print(f"  • Synced: {synced}")
        console.print(f"  • Failed: {failed}")
        console.print(f"  • Total processed: {len(assets_to_sync)}")

        return {
            "tag": tag,
            "total": len(assets),
            "synced": synced,
            "skipped": len(assets) - len(assets_to_sync),
            "failed": failed,
        }

    async def sync_album(
        self, album_name: str, force: bool = False
    ) -> dict:
        """Sync a specific album from Immich to GitHub.

        Args:
            album_name: Name of the album to sync
            force: If True, re-upload even if already synced

        Returns:
            Dictionary with sync statistics
        """
        # Get folder from album mapping
        folder = self.config.album_mappings.get(album_name, album_name)

        console.print(f"\n[bold cyan]Syncing album: {album_name}[/bold cyan]")
        console.print(f"[dim]Target folder: {folder}[/dim]")

        # Warning if album not in config
        if album_name not in self.config.album_mappings:
            console.print(f"[yellow]Warning: Album '{album_name}' not in album_mappings. Using album name as folder.[/yellow]")

        # Fetch albums and find the matching one
        console.print(f"Fetching album '{album_name}' from Immich...")
        albums = await self.immich_client.get_albums()
        album = next((a for a in albums if a.get("albumName") == album_name), None)
        
        if not album:
            console.print(f"[red]Album '{album_name}' not found in Immich[/red]")
            return {
                "album": album_name,
                "total": 0,
                "synced": 0,
                "skipped": 0,
                "failed": 0,
                "error": "Album not found"
            }

        # Fetch assets from the album
        assets = await self.immich_client.get_album_assets(album["id"])
        console.print(f"Found {len(assets)} assets in album '{album_name}'")

        if not assets:
            console.print("[yellow]No assets to sync![/yellow]")
            return {
                "album": album_name,
                "total": 0,
                "synced": 0,
                "skipped": 0,
                "failed": 0,
            }

        # Filter assets based on extension, tags, and sync state
        assets_to_sync = []
        skipped = 0
        for asset in assets:
            # Check file extension first (before downloading)
            file_ext = Path(asset.original_filename).suffix.lower()
            if file_ext not in self.config.allowed_extensions:
                skipped += 1
                continue
            
            # Check excluded tags
            if any(tag in self.config.exclude_tags for tag in asset.tags):
                skipped += 1
                continue
            
            # Check if already synced (unless force=True)
            if not force and self.state.is_synced(asset.id):
                skipped += 1
                continue
            
            assets_to_sync.append(asset)

        if skipped > 0 and not self.dry_run:
            console.print(f"[dim]Skipping {skipped} already synced assets[/dim]")

        if not assets_to_sync:
            console.print("[green]All assets already synced![/green]")
            return {
                "album": album_name,
                "total": len(assets),
                "synced": 0,
                "skipped": len(assets),
                "failed": 0,
            }

        # Dry run mode
        if self.dry_run:
            console.print(f"\n[yellow]DRY RUN: Would sync {len(assets_to_sync)} assets:[/yellow]")
            for i, asset in enumerate(assets_to_sync[:10]):  # Show first 10
                github_path = f"{folder}/{asset.original_filename}"
                console.print(f"  • {asset.original_filename} → {github_path}")
            if len(assets_to_sync) > 10:
                console.print(f"  ... and {len(assets_to_sync) - 10} more")
            return {
                "album": album_name,
                "total": len(assets),
                "synced": 0,
                "skipped": skipped,
                "failed": 0,
                "dry_run": True,
            }

        # Sync assets
        synced = 0
        failed = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Syncing {len(assets_to_sync)} assets...",
                total=len(assets_to_sync),
            )

            for asset in assets_to_sync:
                try:
                    # Download asset to temp directory
                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_path = Path(temp_dir)
                        local_file = await self.immich_client.download_asset(
                            asset.id, temp_path, asset.original_filename
                        )

                        # Check file size
                        if self.config.max_file_size_mb:
                            size_mb = local_file.stat().st_size / (1024 * 1024)
                            if size_mb > self.config.max_file_size_mb:
                                console.print(
                                    f"[yellow]Skipping {asset.original_filename}: "
                                    f"size {size_mb:.1f}MB exceeds limit[/yellow]"
                                )
                                progress.advance(task)
                                continue

                        # Upload to GitHub
                        github_path = f"{folder}/{asset.original_filename}"
                        commit_msg = f"Add {asset.original_filename} from album {album_name}"

                        url = self.sink.upload_file(
                            local_file,
                            github_path,
                            commit_msg,
                            overwrite=force,
                        )

                        # Mark as synced
                        self.state.mark_synced(
                            asset.id,
                            github_path,
                            checksum=asset.checksum,
                            url=url,
                        )
                        synced += 1

                except Exception as e:
                    console.print(f"[red]Failed to sync {asset.original_filename}: {e}[/red]")
                    failed += 1

                progress.advance(task)

        # Commit + push everything staged this cycle, then persist state.
        # Only save state if the push succeeded, so a failed push retries
        # next cycle instead of silently marking assets as synced.
        if synced > 0:
            try:
                self.sink.commit_and_push(
                    f"Sync {synced} photo(s) from album '{album_name}'"
                )
                self.state.save_state()
            except Exception as e:
                console.print(f"[red]Push failed, not saving state (will retry): {e}[/red]")
                # Drop in-memory marks for assets we never actually pushed so
                # they are retried next cycle instead of skipped as "synced".
                self.state.reload()
                failed += synced
                synced = 0

        # Summary
        console.print(f"\n[bold green]Sync completed for album '{album_name}':[/bold green]")
        console.print(f"  • Synced: {synced}")
        console.print(f"  • Failed: {failed}")
        console.print(f"  • Total processed: {len(assets_to_sync)}")

        return {
            "album": album_name,
            "total": len(assets),
            "synced": synced,
            "skipped": skipped,
            "failed": failed,
        }

    async def sync_all_albums(self, force: bool = False) -> List[dict]:
        """Sync all configured albums.

        Args:
            force: If True, re-upload even if already synced

        Returns:
            List of sync results for each album
        """
        results = []
        for album_name in self.config.album_mappings.keys():
            result = await self.sync_album(album_name, force=force)
            results.append(result)
        return results

    async def sync_all_tags(self, force: bool = False) -> List[dict]:
        """Sync all configured tags.

        Args:
            force: If True, re-upload even if already synced

        Returns:
            List of sync results for each tag
        """
        results = []
        for tag in self.config.tag_mappings.keys():
            result = await self.sync_tag(tag, force=force)
            results.append(result)
        return results

    async def close(self) -> None:
        """Close all clients."""
        await self.immich_client.close()

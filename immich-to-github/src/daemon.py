"""Daemon mode for automated background synchronization."""

import asyncio
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import schedule
from rich.console import Console

from .config import Config
from .sync_engine import SyncEngine

console = Console()


class SyncDaemon:
    """Background daemon for automated Immich to GitHub sync."""

    def __init__(self, config: Config):
        """Initialize sync daemon.

        Args:
            config: Configuration object
        """
        self.config = config
        self.running = False
        self.engine: Optional[SyncEngine] = None

    def _run_sync(self):
        """Run a sync cycle."""
        console.print(f"\n[bold cyan]Running scheduled sync at {datetime.now().isoformat()}[/bold cyan]")

        try:
            # Create engine
            self.engine = SyncEngine(self.config, dry_run=False)

            # Run sync
            async def sync():
                # Test connections first
                if not await self.engine.test_connections():
                    console.print("[red]Connection test failed, skipping sync cycle[/red]")
                    await self.engine.close()
                    return

                # Determine which albums to sync (auto_sync_albums, else all mapped)
                albums_to_sync = self.config.auto_sync_albums
                if not albums_to_sync:
                    albums_to_sync = list(self.config.album_mappings.keys())

                # Sync each album
                for album_name in albums_to_sync:
                    try:
                        result = await self.engine.sync_album(album_name, force=False)
                        console.print(
                            f"[green]Album '{album_name}': {result['synced']} synced, "
                            f"{result['skipped']} skipped, {result['failed']} failed[/green]"
                        )
                    except Exception as e:
                        console.print(f"[red]Error syncing album '{album_name}': {e}[/red]")
                        if self.config.retry_on_failure:
                            console.print("[yellow]Will retry in next cycle[/yellow]")

                # Determine which tags to sync
                tags_to_sync = self.config.auto_sync_tags
                if not tags_to_sync:
                    # Sync all configured tags
                    tags_to_sync = list(self.config.tag_mappings.keys())

                # Sync each tag
                for tag in tags_to_sync:
                    try:
                        result = await self.engine.sync_tag(tag, force=False)
                        console.print(
                            f"[green]Tag '{tag}': {result['synced']} synced, "
                            f"{result['skipped']} skipped, {result['failed']} failed[/green]"
                        )
                    except Exception as e:
                        console.print(f"[red]Error syncing tag '{tag}': {e}[/red]")
                        if self.config.retry_on_failure:
                            console.print("[yellow]Will retry in next cycle[/yellow]")

                await self.engine.close()

            # Run async sync
            asyncio.run(sync())

        except Exception as e:
            console.print(f"[red]Sync cycle failed: {e}[/red]")
            if self.engine:
                asyncio.run(self.engine.close())

        console.print("[dim]Sync cycle completed[/dim]")

    def start(self):
        """Start the daemon."""
        if not self.config.automation_enabled:
            console.print("[yellow]Warning: automation.enabled is false in config[/yellow]")
            console.print("[yellow]Starting anyway, but consider updating your config[/yellow]")

        interval_minutes = self.config.automation_interval_minutes
        console.print(f"\n[bold]Starting Immich to GitHub sync daemon[/bold]")
        console.print(f"  • Sync interval: {interval_minutes} minutes")
        console.print(f"  • Repository: {self.config.github_repo}")
        console.print(f"  • Branch: {self.config.github_branch}")
        albums = self.config.auto_sync_albums or list(self.config.album_mappings.keys())
        console.print(f"  • Albums: {', '.join(albums) or '(none)'}")
        console.print(f"  • Tags: {', '.join(self.config.tag_mappings.keys()) or '(none)'}")

        # Schedule sync
        schedule.every(interval_minutes).minutes.do(self._run_sync)

        # Run initial sync
        console.print("\n[bold]Running initial sync...[/bold]")
        self._run_sync()

        # Set up signal handlers for graceful shutdown
        self.running = True
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        console.print(
            f"\n[green]Daemon started. Next sync in {interval_minutes} minutes.[/green]"
        )
        console.print("[dim]Press Ctrl+C to stop[/dim]\n")

        # Main loop
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            self._shutdown()

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        console.print("\n[yellow]Received shutdown signal...[/yellow]")
        self._shutdown()

    def _shutdown(self):
        """Shutdown the daemon gracefully."""
        console.print("[bold]Shutting down daemon...[/bold]")
        self.running = False

        if self.engine:
            console.print("[dim]Closing connections...[/dim]")
            asyncio.run(self.engine.close())

        console.print("[green]Daemon stopped[/green]")
        sys.exit(0)


def start_daemon(config_path: str = "config.yaml"):
    """Start the sync daemon.

    Args:
        config_path: Path to configuration file
    """
    try:
        config = Config(config_path)
        daemon = SyncDaemon(config)
        daemon.start()
    except Exception as e:
        console.print(f"[red]Failed to start daemon: {e}[/red]")
        sys.exit(1)

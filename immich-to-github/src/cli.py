"""Command-line interface for Immich to GitHub sync tool."""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Config
from .sync_engine import SyncEngine
from .daemon import start_daemon

console = Console()


@click.group()
@click.version_option(version=__version__)
def cli():
    """Immich to GitHub sync tool - sync your Immich photos to GitHub based on tags."""
    pass


@cli.command()
@click.option(
    "--album",
    "-a",
    help="Specific album to sync",
    type=str,
)
@click.option(
    "--tag",
    "-t",
    help="Specific tag to sync",
    type=str,
)
@click.option(
    "--all",
    "sync_all",
    is_flag=True,
    help="Sync all configured albums and tags",
)
@click.option(
    "--dry-run",
    "-d",
    is_flag=True,
    help="Preview what would be synced without uploading",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force re-upload even if already synced",
)
@click.option(
    "--config",
    "-c",
    default="config.yaml",
    help="Path to configuration file",
    type=click.Path(exists=True),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output",
)
def sync(album, tag, sync_all, dry_run, force, config, verbose):
    """Sync photos from Immich to GitHub."""

    if not album and not tag and not sync_all:
        console.print("[red]Error: Must specify --album, --tag, or --all[/red]")
        sys.exit(1)

    if sum([bool(album), bool(tag), bool(sync_all)]) > 1:
        console.print("[red]Error: Can only use one of --album, --tag, or --all[/red]")
        sys.exit(1)

    try:
        # Load configuration
        cfg = Config(config)

        # Create sync engine
        engine = SyncEngine(cfg, dry_run=dry_run)

        # Run sync
        async def run_sync():
            # Test connections
            if not await engine.test_connections():
                console.print("[red]Connection test failed. Please check your configuration.[/red]")
                sys.exit(1)

            # Sync
            if sync_all:
                # Sync both albums and tags
                results = []
                if cfg.album_mappings:
                    console.print("\n[bold]Syncing Albums:[/bold]")
                    album_results = await engine.sync_all_albums(force=force)
                    results.extend(album_results)
                if cfg.tag_mappings:
                    console.print("\n[bold]Syncing Tags:[/bold]")
                    tag_results = await engine.sync_all_tags(force=force)
                    results.extend(tag_results)
            elif album:
                result = await engine.sync_album(album, force=force)
                results = [result]
            else:  # tag
                result = await engine.sync_tag(tag, force=force)
                results = [result]

            # Display summary table
            if not dry_run:
                _display_results_table(results)

            await engine.close()

        asyncio.run(run_sync())

    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        if verbose:
            raise
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    "-c",
    default="config.yaml",
    help="Path to configuration file",
    type=click.Path(exists=True),
)
def status(config):
    """Show sync status and statistics."""
    try:
        cfg = Config(config)

        # Load state
        from .state_manager import SyncState

        state = SyncState(cfg.state_file_path, cfg.state_backup_enabled)
        stats = state.get_stats()

        # Display status
        console.print("\n[bold]Sync Status[/bold]")
        console.print(f"  • Total synced assets: {stats['total_synced']}")
        console.print(f"  • Last sync: {stats['last_sync'] or 'Never'}")
        console.print(f"  • State file: {cfg.state_file_path}")

        # Show recent synced assets
        if stats['total_synced'] > 0:
            console.print("\n[bold]Recent synced assets:[/bold]")
            synced = state.get_all_synced_assets()
            # Show last 10
            for asset_id, data in list(synced.items())[-10:]:
                console.print(f"  • {data['github_path']} (synced: {data['synced_at'][:10]})")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    "-c",
    default="config.yaml",
    help="Path to configuration file",
    type=click.Path(exists=True),
)
def test(config):
    """Test connections to Immich and GitHub."""
    try:
        cfg = Config(config)
        engine = SyncEngine(cfg)

        async def run_test():
            success = await engine.test_connections()
            await engine.close()
            if success:
                console.print("\n[bold green]✓ All connections successful![/bold green]")
            else:
                console.print("\n[bold red]✗ Connection test failed[/bold red]")
                sys.exit(1)

        asyncio.run(run_test())

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    "-c",
    default="config.yaml",
    help="Path to configuration file",
    type=click.Path(exists=True),
)
@click.confirmation_option(prompt="Are you sure you want to reset the sync state?")
def reset(config):
    """Reset sync state (clear all tracked assets)."""
    try:
        cfg = Config(config)
        from .state_manager import SyncState

        state = SyncState(cfg.state_file_path, cfg.state_backup_enabled)
        state.reset()
        console.print("[green]Sync state has been reset[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    "-c",
    default="config.yaml",
    help="Path to configuration file",
    type=click.Path(exists=True),
)
def daemon(config):
    """Start background sync daemon for automated syncing."""
    try:
        start_daemon(config)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def _display_results_table(results):
    """Display sync results in a table."""
    table = Table(title="Sync Results")
    table.add_column("Tag/Album", style="cyan")
    table.add_column("Total", style="dim")
    table.add_column("Synced", style="green")
    table.add_column("Skipped", style="yellow")
    table.add_column("Failed", style="red")

    for result in results:
        name = result.get("tag") or result.get("album", "Unknown")
        table.add_row(
            name,
            str(result["total"]),
            str(result["synced"]),
            str(result["skipped"]),
            str(result["failed"]),
        )

    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    cli()

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
    """Show sync status from the per-album manifests in the working clone."""
    try:
        import json

        cfg = Config(config)
        work = Path(cfg.git_work_dir)

        console.print("\n[bold]Sync Status[/bold]")
        console.print(f"  • Working clone: {work}")

        found = False
        for album_name, folder in cfg.album_mappings.items():
            manifest = work / folder / "index.json"
            if not manifest.exists():
                console.print(f"  • {album_name} → {folder}: [dim]not synced yet[/dim]")
                continue
            found = True
            data = json.loads(manifest.read_text())
            count = data.get("count", len(data.get("photos", [])))
            console.print(
                f"  • {album_name} → {folder}: {count} photo(s), "
                f"generated {data.get('generated_at', 'unknown')}"
            )

        if not found:
            console.print("[dim]No manifests found — run a sync first.[/dim]")

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
@click.confirmation_option(
    prompt="Delete the local working clone? Next sync re-bootstraps from Immich."
)
def reset(config):
    """Remove the local working clone so the next sync rebuilds it.

    There is no incremental sync state to clear in the reconcile model — the
    album is the source of truth. This just drops the working clone; the next
    run bootstraps a fresh one and force-pushes a clean snapshot.
    """
    try:
        import shutil

        cfg = Config(config)
        work = Path(cfg.git_work_dir)
        if work.exists():
            shutil.rmtree(work)
            console.print(f"[green]Removed working clone: {work}[/green]")
        else:
            console.print(f"[dim]Nothing to remove ({work} does not exist)[/dim]")

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
    """Display reconcile results in a table."""
    table = Table(title="Reconcile Results")
    table.add_column("Album", style="cyan")
    table.add_column("Total", style="dim")
    table.add_column("Added", style="green")
    table.add_column("Removed", style="red")
    table.add_column("Reordered", style="blue")
    table.add_column("Updated", style="magenta")
    table.add_column("Captions", style="yellow")
    table.add_column("Failed", style="red")

    for result in results:
        name = result.get("album") or result.get("tag", "Unknown")
        table.add_row(
            name,
            str(result.get("total", 0)),
            str(result.get("added", 0)),
            str(result.get("removed", 0)),
            str(result.get("renamed", 0)),
            str(result.get("updated", 0)),
            str(result.get("recaptioned", 0)),
            str(result.get("failed", 0)),
        )

    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    cli()

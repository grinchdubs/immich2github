"""Sync state management to track uploaded assets."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from rich.console import Console

console = Console()


class SyncState:
    """Manages sync state to avoid re-uploading assets."""

    def __init__(self, state_file: Path, backup_enabled: bool = True):
        """Initialize sync state manager.

        Args:
            state_file: Path to state JSON file
            backup_enabled: Whether to create backups of state file
        """
        self.state_file = state_file
        self.backup_enabled = backup_enabled
        self.state: Dict = {
            "last_sync": None,
            "synced_assets": {},
        }
        self._load_state()

    def _load_state(self) -> None:
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    self.state = json.load(f)
                console.print(
                    f"[dim]Loaded sync state: {len(self.state['synced_assets'])} tracked assets[/dim]"
                )
            except json.JSONDecodeError as e:
                console.print(f"[yellow]Warning: Could not parse state file: {e}[/yellow]")
                console.print("[yellow]Starting with empty state[/yellow]")
                self._backup_state()
        else:
            console.print("[dim]No existing sync state found, starting fresh[/dim]")

    def _backup_state(self) -> None:
        """Create a backup of the state file."""
        if not self.backup_enabled or not self.state_file.exists():
            return

        backup_file = self.state_file.with_suffix(".json.backup")
        try:
            shutil.copy2(self.state_file, backup_file)
            console.print(f"[dim]Created state backup: {backup_file}[/dim]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not create backup: {e}[/yellow]")

    def save_state(self) -> None:
        """Save current state to file."""
        try:
            # Backup existing state
            self._backup_state()

            # Save new state
            self.state["last_sync"] = datetime.now().isoformat()
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)

            console.print(f"[dim]Saved sync state to {self.state_file}[/dim]")
        except Exception as e:
            console.print(f"[red]Error saving state: {e}[/red]")
            raise

    def is_synced(self, asset_id: str) -> bool:
        """Check if an asset has been synced.

        Args:
            asset_id: Immich asset ID

        Returns:
            True if asset has been synced, False otherwise
        """
        return asset_id in self.state["synced_assets"]

    def mark_synced(
        self,
        asset_id: str,
        github_path: str,
        checksum: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        """Mark an asset as synced.

        Args:
            asset_id: Immich asset ID
            github_path: Path in GitHub repository
            checksum: Optional checksum of the asset
            url: Optional raw GitHub URL
        """
        self.state["synced_assets"][asset_id] = {
            "github_path": github_path,
            "synced_at": datetime.now().isoformat(),
            "checksum": checksum,
            "url": url,
        }

    def get_synced_path(self, asset_id: str) -> Optional[str]:
        """Get GitHub path for a synced asset.

        Args:
            asset_id: Immich asset ID

        Returns:
            GitHub path if synced, None otherwise
        """
        asset_data = self.state["synced_assets"].get(asset_id)
        if asset_data:
            return asset_data.get("github_path")
        return None

    def get_synced_url(self, asset_id: str) -> Optional[str]:
        """Get GitHub URL for a synced asset.

        Args:
            asset_id: Immich asset ID

        Returns:
            GitHub URL if available, None otherwise
        """
        asset_data = self.state["synced_assets"].get(asset_id)
        if asset_data:
            return asset_data.get("url")
        return None

    def get_all_synced_assets(self) -> Dict[str, Dict]:
        """Get all synced assets.

        Returns:
            Dictionary of asset_id -> asset data
        """
        return self.state["synced_assets"]

    def reset(self) -> None:
        """Reset sync state (clear all tracked assets)."""
        self._backup_state()
        self.state = {
            "last_sync": None,
            "synced_assets": {},
        }
        self.save_state()
        console.print("[yellow]Sync state has been reset[/yellow]")

    def get_stats(self) -> Dict[str, any]:
        """Get statistics about sync state.

        Returns:
            Dictionary with stats
        """
        return {
            "total_synced": len(self.state["synced_assets"]),
            "last_sync": self.state.get("last_sync"),
        }

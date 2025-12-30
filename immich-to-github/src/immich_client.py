"""Immich API client for fetching photos and assets."""

import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
import httpx
from rich.console import Console

console = Console()


class ImmichAsset:
    """Represents an Immich photo asset."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data["id"]
        self.type: str = data["type"]
        self.original_path: Optional[str] = data.get("originalPath")
        self.original_filename: str = data.get("originalFileName", "unknown.jpg")
        self.file_created_at: str = data.get("fileCreatedAt", "")
        self.file_modified_at: str = data.get("fileModifiedAt", "")
        # Safely handle tags - they might be missing or not in the expected format
        tags_data = data.get("tags", [])
        if isinstance(tags_data, list):
            self.tags: List[str] = [
                tag.get("value", tag) if isinstance(tag, dict) else str(tag)
                for tag in tags_data
            ]
        else:
            self.tags: List[str] = []
        self.checksum: Optional[str] = data.get("checksum")

    def __repr__(self) -> str:
        return f"ImmichAsset(id={self.id}, filename={self.original_filename}, tags={self.tags})"


class ImmichClient:
    """Client for interacting with Immich API."""

    def __init__(self, api_url: str, api_key: str):
        """Initialize Immich client.

        Args:
            api_url: Base URL of Immich instance
            api_key: API key for authentication
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            headers={
                "x-api-key": api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def get_all_assets(self) -> List[ImmichAsset]:
        """Fetch all assets from Immich using the search API.

        Returns:
            List of ImmichAsset objects
        """
        try:
            # Use the new Immich search API
            response = await self.client.post(
                f"{self.api_url}/api/search/metadata",
                json={}  # Empty search returns all assets
            )
            response.raise_for_status()
            data = response.json()
            
            # The API returns {assets: {items: [...], total: X}, albums: {...}}
            assets_wrapper = data.get("assets", {})
            assets_data = assets_wrapper.get("items", [])
            console.print(f"[dim]Fetched {len(assets_data)} assets from Immich[/dim]")
            
            # Parse assets with error handling
            parsed_assets = []
            for i, asset in enumerate(assets_data):
                try:
                    parsed_assets.append(ImmichAsset(asset))
                except Exception as e:
                    if i < 2:  # Only show first few errors with full details
                        console.print(f"[yellow]Warning: Failed to parse asset #{i}: {e}[/yellow]")
                    continue
            
            return parsed_assets
        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error fetching assets: {e}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]Error fetching assets: {e}[/red]")
            raise

    async def get_assets_by_tag(self, tag: str) -> List[ImmichAsset]:
        """Fetch assets with a specific tag.

        Args:
            tag: Tag to filter by

        Returns:
            List of ImmichAsset objects with the specified tag
        """
        all_assets = await self.get_all_assets()
        return [asset for asset in all_assets if tag in asset.tags]

    async def get_albums(self) -> List[Dict[str, Any]]:
        """Fetch all albums from Immich.

        Returns:
            List of album dictionaries
        """
        try:
            response = await self.client.get(f"{self.api_url}/api/albums")
            response.raise_for_status()
            albums = response.json()
            return albums
        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error fetching albums: {e}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]Error fetching albums: {e}[/red]")
            raise

    async def get_album_assets(self, album_id: str) -> List[ImmichAsset]:
        """Fetch all assets from a specific album.

        Args:
            album_id: ID of the album

        Returns:
            List of ImmichAsset objects in the album
        """
        try:
            response = await self.client.get(f"{self.api_url}/api/albums/{album_id}")
            response.raise_for_status()
            album_data = response.json()
            assets_data = album_data.get("assets", [])
            console.print(f"[dim]Fetched {len(assets_data)} assets from album[/dim]")
            
            parsed_assets = []
            for asset in assets_data:
                try:
                    parsed_assets.append(ImmichAsset(asset))
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to parse album asset: {e}[/yellow]")
                    continue
            
            return parsed_assets
        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error fetching album assets: {e}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]Error fetching album assets: {e}[/red]")
            raise

    async def download_asset(
        self, asset_id: str, output_path: Path, filename: Optional[str] = None
    ) -> Path:
        """Download an asset from Immich.

        Args:
            asset_id: ID of the asset to download
            output_path: Directory to save the asset
            filename: Optional custom filename (uses original if not provided)

        Returns:
            Path to the downloaded file
        """
        try:
            # Ensure output directory exists
            output_path.mkdir(parents=True, exist_ok=True)

            # Download the asset
            response = await self.client.get(
                f"{self.api_url}/api/assets/{asset_id}/original",
                follow_redirects=True,
            )
            response.raise_for_status()

            # Determine filename
            if filename is None:
                # Try to get filename from Content-Disposition header
                content_disposition = response.headers.get("content-disposition", "")
                if "filename=" in content_disposition:
                    filename = content_disposition.split("filename=")[1].strip('"')
                else:
                    filename = f"{asset_id}.jpg"

            # Write file
            file_path = output_path / filename
            with open(file_path, "wb") as f:
                f.write(response.content)

            return file_path

        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error downloading asset {asset_id}: {e}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]Error downloading asset {asset_id}: {e}[/red]")
            raise

    async def get_asset_info(self, asset_id: str) -> Dict[str, Any]:
        """Get detailed information about an asset.

        Args:
            asset_id: ID of the asset

        Returns:
            Asset information dictionary
        """
        try:
            response = await self.client.get(f"{self.api_url}/api/asset/assetById/{asset_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error fetching asset info: {e}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]Error fetching asset info: {e}[/red]")
            raise

    async def test_connection(self) -> bool:
        """Test connection to Immich API.

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            response = await self.client.get(f"{self.api_url}/api/server/ping")
            return response.status_code == 200
        except Exception as e:
            console.print(f"[red]Connection test failed: {e}[/red]")
            return False


# Context manager support
class ImmichClientContext:
    """Context manager for ImmichClient."""

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key
        self.client: Optional[ImmichClient] = None

    async def __aenter__(self) -> ImmichClient:
        self.client = ImmichClient(self.api_url, self.api_key)
        return self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.close()

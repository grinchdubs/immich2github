"""Immich API client for fetching photos and assets."""

import asyncio
from typing import List, Dict, Any, Optional, Set
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
        # Note: Immich does NOT bump updatedAt on a description edit, so this is
        # unreliable as a caption-change signal — kept only as informational.
        self.updated_at: str = data.get("updatedAt", "")
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

        Uses the paginated search API (``POST /api/search/metadata`` with an
        ``albumIds`` filter) rather than ``GET /api/albums/{id}``. Newer Immich
        versions (3.0+) no longer embed the ``assets`` array in the album detail
        response, so that endpoint returns an empty list even when the album has
        photos. The search API returns them (and works with scoped API keys).

        Args:
            album_id: ID of the album

        Returns:
            List of ImmichAsset objects in the album
        """
        try:
            parsed_assets: List[ImmichAsset] = []
            page = 1
            while True:
                response = await self.client.post(
                    f"{self.api_url}/api/search/metadata",
                    json={"albumIds": [album_id], "page": page, "size": 250},
                )
                response.raise_for_status()
                wrapper = response.json().get("assets", {})
                items = wrapper.get("items", [])

                for asset in items:
                    try:
                        parsed_assets.append(ImmichAsset(asset))
                    except Exception as e:
                        console.print(
                            f"[yellow]Warning: Failed to parse album asset: {e}[/yellow]"
                        )
                        continue

                # Immich returns nextPage as the next page number (str) or null.
                next_page = wrapper.get("nextPage")
                if not next_page or not items:
                    break
                page = int(next_page)

            console.print(f"[dim]Fetched {len(parsed_assets)} assets from album[/dim]")
            return parsed_assets
        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error fetching album assets: {e}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]Error fetching album assets: {e}[/red]")
            raise

    async def get_tags(self) -> List[Dict[str, Any]]:
        """Fetch all tags defined in Immich.

        Returns an empty list (and warns) if the API key lacks ``tag.read`` or
        the request fails — tag-based exclusion is then treated as disabled
        rather than aborting the sync.
        """
        try:
            response = await self.client.get(f"{self.api_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            console.print(
                f"[yellow]Could not read tags ({e}); tag exclusion disabled[/yellow]"
            )
            return []

    async def get_album_excluded_asset_ids(
        self, album_id: str, exclude_tags: List[str]
    ) -> Set[str]:
        """Return IDs of assets in ``album_id`` carrying any of ``exclude_tags``.

        Tags are matched by name/value, case-insensitively. Uses the search API
        with a ``tagIds`` filter (one query per matching tag, unioned) because
        ``search/metadata`` results don't carry per-asset tags. Returns an empty
        set if there are no excluded tags, no matching tags exist, or tags can't
        be read.
        """
        if not exclude_tags:
            return set()
        tags = await self.get_tags()
        if not tags:
            return set()

        wanted = {t.lower() for t in exclude_tags}
        tag_ids = [
            t["id"]
            for t in tags
            if str(t.get("name", "")).lower() in wanted
            or str(t.get("value", "")).lower() in wanted
        ]

        excluded: Set[str] = set()
        for tag_id in tag_ids:
            page = 1
            while True:
                response = await self.client.post(
                    f"{self.api_url}/api/search/metadata",
                    json={
                        "albumIds": [album_id],
                        "tagIds": [tag_id],
                        "page": page,
                        "size": 250,
                    },
                )
                response.raise_for_status()
                wrapper = response.json().get("assets", {})
                items = wrapper.get("items", [])
                for asset in items:
                    excluded.add(asset["id"])
                next_page = wrapper.get("nextPage")
                if not next_page or not items:
                    break
                page = int(next_page)
        return excluded

    async def get_asset_description(self, asset_id: str) -> str:
        """Return an asset's caption (``exifInfo.description``), or "".

        The album search API trims exifInfo, so the caption is only available
        from the per-asset endpoint. Failures degrade to an empty caption
        rather than aborting the sync.
        """
        try:
            response = await self.client.get(f"{self.api_url}/api/assets/{asset_id}")
            response.raise_for_status()
            exif = response.json().get("exifInfo") or {}
            return exif.get("description") or ""
        except Exception as e:
            console.print(
                f"[yellow]Could not read description for {asset_id}: {e}[/yellow]"
            )
            return ""

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

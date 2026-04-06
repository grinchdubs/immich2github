"""Quick script to list all available albums from Immich."""
import asyncio
from src.config import Config
from src.immich_client import ImmichClient


async def list_albums():
    cfg = Config()
    client = ImmichClient(cfg.immich.api_url, cfg.immich.api_key)
    
    try:
        albums = await client.get_albums()
        print('\nAvailable Albums in Immich:')
        print('=' * 70)
        for album in albums:
            name = album.get('albumName', 'Unnamed')
            count = album.get('assetCount', 0)
            album_id = album.get('id', 'N/A')
            print(f'  {name:<35} ({count:>3} photos)  ID: {album_id[:8]}...')
        print('=' * 70)
        print(f'Total: {len(albums)} albums')
    finally:
        await client.close()


if __name__ == '__main__':
    asyncio.run(list_albums())

# Immich to GitHub Photo Sync

## Project Overview
This project syncs photos from Immich (self-hosted photo management) to a GitHub repository for display on a static website. Photos are organized by albums in Immich and mapped to folders in the GitHub repo.

## System Architecture
- **Immich Server**: Running at `http://grnchnas:30041` (Tailscale network)
- **GitHub Repo**: `grinchdubs/grnch.xyz_photos` (stores synced photos)
- **Website Repo**: `grinchdubs/grinchdubs.github.io` (displays photos from raw GitHub URLs)
- **Python Environment**: Virtual environment at `.venv/` with Python 3.14.0

## Configuration Files
- `.env` - API credentials (Immich API key, GitHub token)
- `config.yaml` - Album mappings and sync settings
- `.sync_state.json` - Tracks synced assets to avoid duplicates

## Album Mappings
Current album mappings in `config.yaml`:
```yaml
album_mappings:
  Pen-plotting: plotting
  Risograph: risograph
  Prints: prints
  Zines: zines
```

## How to Sync Photos

### Prerequisites
1. Make sure you're in the project directory
2. Activate the virtual environment (or use full path to python.exe)
3. Ensure Immich and GitHub credentials are set in `.env`

### Sync Commands

**Sync all configured albums:**
```bash
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli sync --all
```

**Sync a specific album:**
```bash
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli sync --album Zines
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli sync --album Prints
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli sync --album Risograph
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli sync --album Pen-plotting
```

**Dry run (preview without uploading):**
```bash
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli sync --all --dry-run
```

**Force re-upload (ignore sync state):**
```bash
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli sync --all --force
```

**Test connections:**
```bash
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe -m src.cli test
```

### Generate Markdown for Website

After syncing, generate markdown for the website:
```bash
D:/Users/PC/Documents/GitHub/pwnagotchi-projects/immich2github/.venv/Scripts/python.exe generate_markdown.py
```

This creates `photo_markdown.txt` with image links ready to paste into the website's `plotting.md` file.

## File Limitations
- **Max file size**: 100MB (configurable in config.yaml)
- **GitHub API limit**: Files must be < 100MB via API
- Videos larger than the limit are automatically skipped

## Current Sync Statistics
As of last sync:
- **Pen-plotting**: 409 photos synced
- **Risograph**: 77 photos synced
- **Prints**: 25 photos synced  
- **Zines**: 10 photos synced

## Important Notes
- The sync engine tracks state in `.sync_state.json` - don't delete this unless you want to re-sync everything
- Synced photos are uploaded to `https://raw.githubusercontent.com/grinchdubs/grnch.xyz_photos/main/[folder]/[filename]`
- The tool skips already-synced photos automatically (unless `--force` is used)
- Videos over 100MB are skipped and noted in the output

## API Endpoints Used
- Immich: `/api/server/ping`, `/api/albums`, `/api/albums/{id}`, `/api/assets/{id}/original`
- GitHub: Uses PyGithub library for file uploads via REST API

## Troubleshooting
- If connection fails, check Tailscale is running and Immich is accessible
- If GitHub upload fails with 403, regenerate GitHub token with `repo` scope
- If photos aren't syncing, check album names match exactly in Immich
- State file backup is created as `.sync_state.json.backup` before each sync

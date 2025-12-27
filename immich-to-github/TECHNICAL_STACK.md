# Technical Stack - Immich to GitHub Sync Tool

## Core Technology: Python 3.10+

**Rationale:** Python offers the best balance of simplicity, efficiency, and library support for this use case.

## Key Dependencies

### API & Integration
- **httpx** - Modern async HTTP client for Immich API calls
- **PyGithub** - Official GitHub API wrapper for repository operations
- **python-dotenv** - Environment variable management for API keys

### CLI & Automation
- **click** - Elegant CLI framework for manual mode
- **schedule** - Simple job scheduling for automated mode
- **rich** - Beautiful terminal output and progress indicators

### Data & Configuration
- **pydantic** - Data validation and settings management
- **PyYAML** - Configuration file handling
- **pathlib** - Modern file path handling (stdlib)

## Architecture Components

### 1. Immich Client (`immich_client.py`)
- Authenticate with Immich API
- Fetch photos by tags
- Download photo assets
- Handle pagination and rate limiting

### 2. GitHub Client (`github_client.py`)
- Authenticate with GitHub API
- Create/update repository files
- Manage folder structure based on tags
- Generate commit messages

### 3. Sync Engine (`sync_engine.py`)
- Orchestrate the sync workflow
- Map Immich tags → GitHub folders
- Track sync state (avoid re-uploading)
- Generate markdown references

### 4. CLI Interface (`cli.py`)
- Manual sync command
- Configuration management
- Dry-run mode
- Verbose logging

### 5. Automation Service (`daemon.py`)
- Background sync scheduler
- Configurable intervals
- Error handling and retry logic
- Notification system (optional)

## Data Flow

```
Immich API → Fetch Tagged Photos → Download → Map Tags to Folders →
Upload to GitHub → Update Sync State → Generate Markdown
```

## Configuration

**config.yaml**
```yaml
immich:
  api_url: "https://your-immich-instance.com"
  api_key: "${IMMICH_API_KEY}"

github:
  repo: "grinchdubs/grnch.xyz_photos"
  token: "${GITHUB_TOKEN}"
  branch: "main"

sync:
  tag_mappings:
    "pen-plotting": "plotting"
    "laser-engraving": "laser"
  exclude_tags: ["private", "draft"]

automation:
  enabled: false
  interval_minutes: 60
```

## Deployment Options

### Manual Mode
```bash
immich-sync --tags pen-plotting --dry-run
immich-sync --sync-all
```

### Automated Mode
1. **Local Cron Job** - Run on personal machine/server
2. **GitHub Actions** - Scheduled workflow (if Immich is publicly accessible)
3. **Docker Container** - Containerized daemon for easy deployment

## State Management

**sync_state.json** - Tracks what's been synced
```json
{
  "last_sync": "2025-12-27T10:30:00Z",
  "synced_assets": {
    "photo-uuid-123": {
      "github_path": "plotting/image1.jpg",
      "synced_at": "2025-12-27T10:30:00Z"
    }
  }
}
```

## Security Considerations

- API keys stored in environment variables
- Support for `.env` file (git-ignored)
- No credentials in code or config files
- GitHub token with minimal required permissions
- Optional encryption for sync state file

## Performance Optimizations

- Async HTTP requests for concurrent downloads
- Skip already-synced photos (hash comparison)
- Batch GitHub API calls where possible
- Configurable rate limiting
- Progress indicators for large syncs

## Testing Strategy

- Unit tests for each client module
- Integration tests with mock APIs
- CLI tests with click.testing
- Dry-run mode for safe testing

## Future Enhancements

- Support for albums (in addition to tags)
- Image optimization/resizing before upload
- Multi-repository support
- Web dashboard for monitoring
- Webhook integration for real-time sync

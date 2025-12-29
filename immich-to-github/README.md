# Immich to GitHub Sync Tool

Automatically sync photos from your Immich instance to GitHub based on tags. Perfect for managing photo portfolios, blogs, and project galleries.

## Features

- **Tag-based Organization** - Immich tags automatically map to GitHub folders
- **Manual & Automated Modes** - Run on-demand or schedule automatic syncs
- **Smart Sync** - Only uploads new photos, skips duplicates
- **Dry-run Mode** - Preview changes before uploading
- **Markdown Generation** - Get ready-to-paste markdown image references
- **Progress Tracking** - Beautiful terminal output with progress indicators

## Quick Start

### 🐳 Docker Deployment (Recommended for Local Immich)

**Perfect for running inside your network where Immich is accessible!**

```bash
# Clone and setup
git clone https://github.com/grinchdubs/immich2github.git
cd immich2github/immich-to-github

# Configure
cp .env.example .env
cp config.yaml.example config.yaml
# Edit .env and config.yaml with your settings

# Create data directory
mkdir -p data

# Run daemon mode (automated background sync)
docker-compose up -d

# OR run one-time sync
docker-compose run --rm immich-sync python -m src.cli sync --all --config /app/config.yaml
```

📖 **See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for complete Docker deployment guide**

### 🐍 Python Installation

### Prerequisites

- Python 3.10 or higher
- Immich instance with API access
- GitHub personal access token
- GitHub repository for storing photos

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/immich-to-github.git
cd immich-to-github

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API credentials

# Copy and configure settings
cp config.yaml.example config.yaml
# Edit config.yaml with your preferences
```

### Configuration

1. **Get your Immich API key:**
   - Log into Immich
   - Go to Settings → API Keys
   - Create a new API key

2. **Get your GitHub token:**
   - Go to GitHub Settings → Developer settings → Personal access tokens
   - Create token with `repo` scope

3. **Edit `.env`:**
```env
IMMICH_API_URL=https://your-immich-instance.com
IMMICH_API_KEY=your_immich_api_key
GITHUB_TOKEN=your_github_token
```

4. **Edit `config.yaml`:**
```yaml
github:
  repo: "username/photo-repo"
  branch: "main"

sync:
  tag_mappings:
    "pen-plotting": "plotting"
    "photography": "photos"
```

## Usage

### Manual Sync

```bash
# Sync photos with specific tag
python -m src.cli sync --tag pen-plotting

# Sync all configured tags
python -m src.cli sync --all

# Preview what will be synced (dry-run)
python -m src.cli sync --tag pen-plotting --dry-run

# Verbose output
python -m src.cli sync --tag pen-plotting --verbose
```

### Automated Sync (Daemon Mode)

```bash
# Start background sync service
python -m src.cli daemon

# Stop daemon
python -m src.cli daemon stop
```

### Generate Markdown

```bash
# Generate markdown for synced photos
python -m src.cli generate-markdown --tag pen-plotting
```

## How It Works

1. **Fetch** - Connects to Immich API and fetches photos with specified tags
2. **Map** - Maps Immich tags to GitHub folder paths
3. **Download** - Downloads photo assets from Immich
4. **Upload** - Commits and pushes photos to GitHub repository
5. **Track** - Records sync state to avoid re-uploading

## Project Structure

```
immich-to-github/
├── src/
│   ├── immich_client.py      # Immich API integration
│   ├── github_client.py      # GitHub API integration
│   ├── sync_engine.py        # Core sync logic
│   ├── state_manager.py      # Sync state tracking
│   ├── markdown_generator.py # Markdown generation
│   ├── daemon.py             # Background service
│   └── cli.py                # CLI interface
├── tests/                    # Test suite
├── config.yaml.example       # Configuration template
├── .env.example             # Environment variables template
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Documentation

- [Technical Stack](TECHNICAL_STACK.md) - Architecture and technology choices
- [Project Plan](PROJECT_PLAN.md) - Development roadmap and phases
- [Usage Guide](USAGE.md) - Detailed usage examples (coming soon)

## Development Status

This project is currently in **Phase 1 - Foundation & Core Sync**

- [x] Repository structure
- [x] Technical documentation
- [x] Project planning
- [ ] Immich API client
- [ ] GitHub API client
- [ ] Core sync engine
- [ ] CLI interface
- [ ] Configuration system

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for full roadmap.

## Contributing

This is a personal project, but suggestions and bug reports are welcome! Please open an issue to discuss proposed changes.

## License

MIT License - See LICENSE file for details

## Acknowledgments

- [Immich](https://immich.app/) - Amazing self-hosted photo management
- [PyGithub](https://github.com/PyGithub/PyGithub) - GitHub API wrapper
- [Click](https://click.palletsprojects.com/) - CLI framework

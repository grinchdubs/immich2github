# Docker Deployment Guide

This guide explains how to deploy the Immich to GitHub sync tool using Docker. This is ideal for running the tool inside your local network where your Immich server is accessible.

## Prerequisites

- Docker and Docker Compose installed
- Access to your local Immich instance
- GitHub personal access token with `repo` scope
- Network access to both Immich and GitHub

## Quick Start

### 1. Clone and Navigate

```bash
git clone https://github.com/grinchdubs/immich2github.git
cd immich2github/immich-to-github
```

### 2. Configure Environment Variables

Create `.env` file from the example:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
IMMICH_API_URL=http://your-immich-server:2283  # Use your local Immich URL
IMMICH_API_KEY=your_immich_api_key_here
GITHUB_TOKEN=your_github_personal_access_token_here
```

**Getting your credentials:**
- **Immich API Key**: Immich Settings → API Keys → Create new key
- **GitHub Token**: GitHub Settings → Developer settings → Personal access tokens → Generate new token (needs `repo` scope)

### 3. Configure Sync Settings

Create `config.yaml` from the example:

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` to customize:
- Repository name
- Tag mappings (Immich tags → GitHub folders)
- File size limits, extensions, etc.

### 4. Create Data Directory

```bash
mkdir -p data
```

This directory will store the sync state file.

## Deployment Options

### Option A: Daemon Mode (Automated Background Sync)

Run continuous background syncing on a schedule:

```bash
# Build and start the daemon
docker-compose up -d

# View logs
docker-compose logs -f

# Stop daemon
docker-compose down
```

The daemon will:
- Run an initial sync immediately
- Continue syncing on the configured interval (default: 60 minutes)
- Restart automatically if it crashes

### Option B: Manual One-Time Sync

Run a single sync operation:

```bash
# Test connections first
docker-compose run --rm immich-sync python -m src.cli test --config /app/config.yaml

# Dry-run (preview what will be synced)
docker-compose run --rm immich-sync python -m src.cli sync --all --dry-run --config /app/config.yaml

# Actual sync
docker-compose run --rm immich-sync python -m src.cli sync --all --config /app/config.yaml

# Sync specific tag
docker-compose run --rm immich-sync python -m src.cli sync --tag pen-plotting --config /app/config.yaml
```

### Option C: Scheduled with Cron

Add to your system's crontab to run daily at 2 AM:

```bash
0 2 * * * cd /path/to/immich-to-github && docker-compose run --rm immich-sync python -m src.cli sync --all --config /app/config.yaml
```

## Docker Commands Reference

### Build/Rebuild Image

```bash
# Build the image
docker-compose build

# Rebuild without cache
docker-compose build --no-cache
```

### View Logs

```bash
# Follow logs in real-time
docker-compose logs -f

# View last 100 lines
docker-compose logs --tail=100
```

### Check Status

```bash
# View sync status
docker-compose run --rm immich-sync python -m src.cli status --config /app/config.yaml

# Check if container is running
docker-compose ps
```

### Stop and Remove

```bash
# Stop daemon
docker-compose down

# Stop and remove volumes (WARNING: deletes sync state)
docker-compose down -v
```

## File Structure

```
immich-to-github/
├── Dockerfile              # Docker image definition
├── docker-compose.yml      # Docker Compose configuration
├── .env                    # Your API credentials (git-ignored)
├── config.yaml             # Sync configuration (git-ignored)
├── data/                   # Persistent data directory
│   └── .sync_state.json   # Sync state tracking
└── src/                    # Application source code
```

## Networking Considerations

### Local Immich Server

If your Immich server is running on the same host:

```env
# Use host.docker.internal to access host machine
IMMICH_API_URL=http://host.docker.internal:2283
```

Or add to `docker-compose.yml`:

```yaml
services:
  immich-sync:
    network_mode: "host"  # Use host network
```

### Immich in Another Docker Container

If Immich is running in Docker, create a shared network:

```bash
# Create network
docker network create immich-network

# Add to both docker-compose files
networks:
  default:
    external:
      name: immich-network
```

## Troubleshooting

### Can't connect to Immich

```bash
# Test connection from inside container
docker-compose run --rm immich-sync python -m src.cli test --config /app/config.yaml

# Check if Immich URL is accessible
docker-compose run --rm immich-sync curl http://your-immich-server:2283/api/server-info/ping
```

### Permission errors on data directory

```bash
# Fix permissions
sudo chown -R $USER:$USER data/
chmod 755 data/
```

### View detailed error logs

```bash
# Run with verbose output
docker-compose run --rm immich-sync python -m src.cli sync --all --verbose --config /app/config.yaml
```

### Reset sync state

```bash
# Reset state (will re-sync everything)
docker-compose run --rm immich-sync python -m src.cli reset --config /app/config.yaml

# Or manually delete state file
rm data/.sync_state.json
```

## Security Best Practices

1. **Keep `.env` secure**: Never commit `.env` to git
2. **Use read-only volumes**: Config files are mounted read-only in docker-compose.yml
3. **Limit GitHub token scope**: Only grant `repo` permission, nothing more
4. **Rotate API keys**: Regenerate Immich API key and GitHub token periodically
5. **Network isolation**: Use Docker networks to isolate the container

## Updating the Application

```bash
# Pull latest changes
git pull origin main

# Rebuild the Docker image
docker-compose build

# Restart daemon
docker-compose down
docker-compose up -d
```

## Advanced: Production Deployment

For production use, consider:

1. **Use Docker secrets** instead of `.env` file
2. **Set up monitoring** with Prometheus/Grafana
3. **Configure log rotation** to prevent disk fill
4. **Set resource limits** in docker-compose.yml:

```yaml
services:
  immich-sync:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
```

## Support

For issues, check:
- Application logs: `docker-compose logs`
- GitHub Issues: https://github.com/grinchdubs/immich2github/issues
- README.md for general usage

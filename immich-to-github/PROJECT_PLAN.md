# Project Plan - Immich to GitHub Sync Tool

## Project Overview

**Goal:** Create a flexible sync tool that transfers photos from Immich to GitHub based on tags, supporting both manual and automated workflows.

**Target User:** Solo developer managing a photo portfolio/blog with Immich

**Success Criteria:**
- Photos tagged in Immich automatically organize into GitHub folders
- Can run manually on-demand or on a schedule
- Generates markdown-ready image URLs
- Maintains sync state to avoid duplicates
- Simple configuration and setup

## Development Phases

### Phase 1: Foundation & Core Sync (MVP)

**Deliverables:**
- [x] Repository structure
- [ ] Basic Immich API client (read-only)
- [ ] Basic GitHub API client (upload files)
- [ ] Simple tag-to-folder mapping
- [ ] Manual sync command
- [ ] Configuration file support
- [ ] Basic error handling

**User Story:**
> As a user, I can run `immich-sync --tag pen-plotting` and have all photos with that tag uploaded to `grnch.xyz_photos/plotting/` folder on GitHub.

**Estimated Complexity:** Medium
**Core Files:**
- `immich_client.py`
- `github_client.py`
- `sync_engine.py`
- `cli.py`
- `config.yaml.example`

### Phase 2: Smart Sync & State Management

**Deliverables:**
- [ ] Sync state tracking (JSON file)
- [ ] Skip already-synced photos
- [ ] Hash-based duplicate detection
- [ ] Dry-run mode
- [ ] Verbose logging
- [ ] Progress indicators

**User Story:**
> As a user, when I run sync again, it only uploads new photos and shows me what will be synced before committing.

**Estimated Complexity:** Medium
**Core Files:**
- `state_manager.py`
- Enhanced `sync_engine.py`
- Enhanced `cli.py`

### Phase 3: Automation & Scheduling

**Deliverables:**
- [ ] Daemon mode for background sync
- [ ] Configurable sync intervals
- [ ] Retry logic for failed uploads
- [ ] Basic notification (stdout/log file)
- [ ] Graceful shutdown handling

**User Story:**
> As a user, I can run `immich-sync daemon` and have it automatically sync new tagged photos every hour without manual intervention.

**Estimated Complexity:** Medium
**Core Files:**
- `daemon.py`
- Enhanced `config.yaml`

### Phase 4: Markdown Generation & Polish

**Deliverables:**
- [ ] Markdown snippet generation
- [ ] Organize by date/custom sorting
- [ ] Update existing markdown files (optional)
- [ ] Image metadata preservation
- [ ] Comprehensive documentation
- [ ] Installation script

**User Story:**
> As a user, after sync, I get a markdown snippet I can paste directly into my plotting.md file with properly formatted image URLs.

**Estimated Complexity:** Low-Medium
**Core Files:**
- `markdown_generator.py`
- Enhanced `cli.py`
- `README.md`
- `USAGE.md`

## Implementation Details

### Directory Structure
```
immich-to-github/
├── src/
│   ├── __init__.py
│   ├── immich_client.py      # Immich API wrapper
│   ├── github_client.py      # GitHub API wrapper
│   ├── sync_engine.py        # Core sync logic
│   ├── state_manager.py      # Sync state tracking
│   ├── markdown_generator.py # Markdown output
│   ├── daemon.py             # Background service
│   └── cli.py                # Click CLI interface
├── tests/
│   ├── test_immich_client.py
│   ├── test_github_client.py
│   └── test_sync_engine.py
├── config.yaml.example
├── .env.example
├── requirements.txt
├── setup.py
├── README.md
├── TECHNICAL_STACK.md
├── PROJECT_PLAN.md
└── USAGE.md
```

### Configuration Flow

1. **Environment Variables** (`.env`)
   - `IMMICH_API_URL`
   - `IMMICH_API_KEY`
   - `GITHUB_TOKEN`

2. **Config File** (`config.yaml`)
   - Tag mappings
   - Repository settings
   - Automation settings

3. **CLI Arguments** (override config)
   - `--tag`, `--dry-run`, `--verbose`

### CLI Commands

```bash
# Setup
immich-sync init                    # Interactive config setup

# Manual sync
immich-sync sync --tag pen-plotting # Sync specific tag
immich-sync sync --all              # Sync all configured tags
immich-sync sync --dry-run          # Preview without uploading

# Automation
immich-sync daemon                  # Start background service
immich-sync daemon stop             # Stop daemon

# Utilities
immich-sync status                  # Show sync state
immich-sync generate-markdown       # Generate markdown from synced photos
immich-sync config validate         # Validate configuration
```

## Technical Decisions

### Why Python?
- Rich ecosystem for API clients
- Simple async/await for concurrent operations
- Great CLI libraries (click)
- Easy to package and distribute
- Familiar to most developers

### Why Click over Argparse?
- More elegant syntax
- Better help formatting
- Built-in support for complex command groups
- Excellent testing support

### Why PyGithub?
- Official Python library for GitHub API
- Handles authentication and rate limiting
- Well-maintained and documented

### State Management Approach
- JSON file for simplicity (can upgrade to SQLite later)
- Store asset UUID + GitHub path mapping
- Include timestamps for audit trail
- Support for manual state reset

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| API rate limits | Implement backoff, batch requests, cache responses |
| Large photo uploads | Add size limits, optional compression, chunked uploads |
| Network failures | Retry logic with exponential backoff |
| Credential leaks | Use environment variables, add .env to .gitignore |
| Breaking API changes | Pin dependency versions, add integration tests |
| Duplicate uploads | State tracking with hash comparison |

## Testing Strategy

### Unit Tests
- Mock API responses
- Test tag mapping logic
- Test state management
- Test markdown generation

### Integration Tests
- Test with real Immich instance (dev environment)
- Test GitHub uploads to test repository
- Test full sync workflow

### Manual Testing Checklist
- [ ] Sync single tagged photo
- [ ] Sync multiple tags
- [ ] Resume interrupted sync
- [ ] Dry-run mode accuracy
- [ ] Daemon mode stability
- [ ] Error handling for invalid credentials
- [ ] Handle photos with no tags
- [ ] Handle photos with multiple tags

## Success Metrics

- **Reliability:** 99%+ successful syncs
- **Performance:** Process 100 photos in <5 minutes
- **Usability:** Setup in <10 minutes
- **Maintainability:** <500 lines of core logic
- **Testability:** >80% code coverage

## Post-Launch Enhancements

1. **Album support** - Sync entire albums
2. **Image optimization** - Resize before upload
3. **Web UI** - Simple dashboard for monitoring
4. **Multi-repo** - Sync to different repos based on tags
5. **Webhooks** - Real-time sync on photo upload
6. **Docker image** - Easy deployment
7. **GitHub Action** - Scheduled sync in CI/CD

## Timeline Estimate

- **Phase 1 (MVP):** 1-2 days
- **Phase 2 (Smart Sync):** 1 day
- **Phase 3 (Automation):** 1 day
- **Phase 4 (Polish):** 1 day
- **Testing & Documentation:** 1 day

**Total:** ~5-6 days of focused development

## Getting Started

Next steps:
1. Set up development environment
2. Create Immich API test credentials
3. Create GitHub test repository
4. Implement Phase 1 MVP
5. Test with real data
6. Iterate based on usage

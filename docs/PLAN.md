# Immich to GRNCH.xyz Sync via Gitea Actions: Execution Plan

## Phase 1: Stabilize the Gitea Runner

- [ ] Get logs from the runner container
  - Docker: `docker logs <runner_container_name> --tail 100`
  - k3s app: `k3s kubectl logs -n ix-gitea-runner <pod_name>`
- [ ] Identify the crash cause from logs (common ones below)
  - [ ] Registration token invalid or missing
  - [ ] `GITEA_INSTANCE_URL` unreachable from runner
  - [ ] Stale `.runner` config from a previous failed registration
  - [ ] Docker socket not mounted (`/var/run/docker.sock`)
  - [ ] OOMKilled (check `dmesg` / pod events)
- [ ] Generate a fresh registration token in Gitea
  - Admin or Org settings -> Actions -> Runners -> Create new runner
- [ ] Update runner env vars / config with correct token and instance URL
- [ ] If stale config exists, delete `.runner` file / config volume and let it re-register
- [ ] Restart runner and confirm it shows "Idle" in Gitea Actions Runners list
- [ ] Run a trivial test workflow (e.g. `echo hello`) to confirm execution works

## Phase 2: Prep Immich Access

- [ ] Log into Immich, go to Account Settings -> API Keys
- [ ] Generate a new API key, save it somewhere safe temporarily
- [ ] Note Immich internal URL and port (e.g. `http://immich.local:2283`)
- [ ] Identify the album(s) to sync, note each Album ID
  - Get via `GET /api/albums` with the API key

## Phase 3: Build the Sync Script

- [ ] Create/choose repo for the sync script (can live in grnch.xyz repo or its own repo)
- [ ] Write Python script that:
  - [ ] Calls `GET /api/albums/{id}` to list assets in the album
  - [ ] Compares against a local state file (`synced_assets.json`) to find new assets
  - [ ] Downloads new assets via `GET /api/assets/{id}/original`
  - [ ] Resizes/optimizes images with Pillow for web use
  - [ ] Saves images to `assets/images/gallery/`
  - [ ] Updates Jekyll data file `_data/gallery.yml` with new entries
  - [ ] Updates `synced_assets.json` with newly synced asset IDs
- [ ] Add a `requirements.txt` (e.g. `requests`, `Pillow`)
- [ ] Test script locally against Immich before wiring into CI

## Phase 4: Configure Gitea Secrets

- [ ] In repo Settings -> Actions -> Secrets, add:
  - [ ] `IMMICH_API_KEY`
  - [ ] `IMMICH_URL`
  - [ ] `GITHUB_PAT` (or deploy key with write access to grnch.xyz repo)

## Phase 5: Write the Gitea Actions Workflow

- [ ] Create `.gitea/workflows/sync-immich.yml`
  - [ ] Trigger: `schedule` (cron) and `workflow_dispatch`
  - [ ] Steps:
    - [ ] Checkout repo
    - [ ] Set up Python
    - [ ] Install dependencies from `requirements.txt`
    - [ ] Run sync script with secrets as env vars
    - [ ] Check for git diff; if changes exist, commit and push to GitHub remote

## Phase 6: Network and Firewall Check

- [ ] Confirm runner container can reach Immich's internal address (test with `curl` from inside container)
- [ ] Confirm runner container has outbound HTTPS access to github.com

## Phase 7: Manual Test Run

- [ ] Trigger workflow manually via `workflow_dispatch`
- [ ] Verify new images appear in repo
- [ ] Verify `_data/gallery.yml` updates correctly
- [ ] Verify GitHub Pages build succeeds with new content
- [ ] Spot check site renders gallery images correctly

## Phase 8: Enable Automation

- [ ] Set cron schedule to desired frequency (e.g. daily at 6am: `0 6 * * *`)
- [ ] Monitor first few scheduled runs for failures
- [ ] Done; ongoing maintenance only

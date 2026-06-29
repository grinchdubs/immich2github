# CLAUDE.md: Immich to GRNCH.xyz Gallery Sync

## Project Overview

Automate syncing photos from an Immich album into the grnch.xyz Jekyll site
(GitHub Pages), using a Gitea Actions runner hosted on TrueNAS Scale.

## Environment

- Gitea instance: self-hosted on TrueNAS Scale (app `ix-gitea`)
- Gitea Actions runner: self-hosted on same TrueNAS Scale box (Docker or k3s app)
- Immich instance: self-hosted, internal network access only
- Target site repo: grnch.xyz (Jekyll, hosted on GitHub Pages)
- NAS pool name: Lepus

## Key Endpoints / Config Values

Fill these in as you go:

- Immich URL: `____________`
- Immich Album ID(s): `____________`
- Gitea repo for sync script: `____________`
- GitHub repo for grnch.xyz: `____________`
- Jekyll gallery data file path: `_data/gallery.yml`
- Image output directory: `assets/images/gallery/`
- State file (synced asset tracking): `synced_assets.json`

## Secrets (stored in Gitea repo Settings -> Actions -> Secrets)

- `IMMICH_API_KEY`: Immich API key (Account Settings -> API Keys)
- `IMMICH_URL`: Immich base URL, internal address
- `GITHUB_PAT`: Personal access token or deploy key with write access to grnch.xyz repo

## Workflow File Location

`.gitea/workflows/sync-immich.yml`

- Triggers: `schedule` (cron) and `workflow_dispatch`
- Steps: checkout -> setup python -> install deps -> run sync script -> commit/push if changed

## Sync Script Logic (high level)

1. Authenticate to Immich API with `IMMICH_API_KEY`
2. `GET /api/albums/{id}` to list current assets
3. Diff against `synced_assets.json` to find new assets
4. `GET /api/assets/{id}/original` to download new images
5. Resize/optimize with Pillow
6. Save to `assets/images/gallery/`
7. Append entries to `_data/gallery.yml`
8. Update `synced_assets.json`
9. Workflow commits and pushes changes to GitHub remote, triggering Pages rebuild

## Common Troubleshooting

### Runner crash looping
- Check logs: `docker logs <container>` or `k3s kubectl logs -n ix-gitea-runner <pod>`
- Causes: bad registration token, unreachable `GITEA_INSTANCE_URL`, stale `.runner` config,
  missing docker socket mount, OOMKilled

### Runner can't reach Immich
- Confirm internal network/firewall allows runner container -> Immich container/VM
- Test with `curl` from inside the runner container

### Push to GitHub fails
- Check `GITHUB_PAT` has correct repo write scope and hasn't expired
- Confirm git remote URL uses the PAT correctly (e.g. `https://<user>:<PAT>@github.com/...`)

## Status / Progress Log

Use this section to track where things stand across sessions.

- [ ] Phase 1: Runner stable
- [ ] Phase 2: Immich access ready
- [ ] Phase 3: Sync script written and tested locally
- [ ] Phase 4: Secrets configured
- [ ] Phase 5: Workflow file written
- [ ] Phase 6: Network checks passed
- [ ] Phase 7: Manual run successful
- [ ] Phase 8: Cron automation enabled

## Reference

See `PLAN.md` in this same directory for the detailed step-by-step checklist.

# HANDOFF — Immich → grnch.xyz Photo Sync (internal-staging redesign)

> **Purpose of this doc:** complete, self-contained context so a fresh AI (or human)
> can pick this up cold without re-deriving anything. Read it top to bottom before
> touching code. Dates and facts are current as of **2026-06-28**.

---

## 0. TL;DR (read this first)

**Goal:** When the user adds a photo to the Immich album **"Risograph"**, it should
automatically appear on their website **grnch.xyz** (a Jekyll / GitHub Pages site),
with **zero manual steps**.

**Where we are:** A working sync tool (`immich2github`) exists and is patched to sync
albums. Its Docker image builds in GitHub Actions and is published **public** at
`ghcr.io/grinchdubs/immich2github:latest`. The user tried to run it as a TrueNAS
"Custom App" (the **daemon**) but reports **it may be broken / needs to be redone** —
treat the TrueNAS deployment as **unverified, probably needs a clean redo**.

**The new direction (THIS is what to build):** Instead of the daemon pushing photos
straight to GitHub, we are inserting an **internal staging loop** so the user can
preview changes on their LAN before anything goes public:

```
Add photo to "Risograph" album in Immich
        │
        ▼
  immich2github DAEMON  (container on TrueNAS, polls Immich every 2 min)
        │  git push   ◄── THE KEY CODE CHANGE (Phase 1): switch sink from
        ▼              GitHub Contents-API → plain `git push` to ANY remote
  GITEA SERVER  (local; hosts a staging copy of the `grnch.xyz_photos` repo)
        │  on-push triggers
        ▼
  GITEA ACTIONS RUNNER  (rebuilds the Jekyll site)   ◄── finally gives the
        │                                                orphaned runner a job
        ▼
  JEKYLL PREVIEW at  grnchnix:9105   ◄── user eyeballs it here, on the LAN
        │
        ▼
  (LATER, deferred) promote to GitHub → public grnch.xyz on GitHub Pages
```

**Why this shape:** Immich has **no webhooks** (confirmed; open feature requests
immich #13181, #1671), so "on upload" is impossible — polling every 2 min is the
deliberate, correct design. We are **not** forking Immich (the user asked; we agreed
it's a bad idea — permanent maintenance of a fast-moving fork to save <2 min latency).

---

## 1. Machines & network topology

| Host | Role | Address |
|------|------|---------|
| **TrueNAS Scale box** | Runs **Immich** AND the **immich2github daemon** container. NAS pool is named **`Lepus`**. | Immich API at `http://192.191.5.109:30041` |
| **grnchnix** | **Separate machine.** Runs the **Jekyll live preview** of grnch.xyz. Candidate host for the **Gitea Actions runner** + the preview rebuild. | preview at `grnchnix:9105` |
| **Gitea server** | Local git host. Will hold the **staging** `grnch.xyz_photos` repo. Runs on the **NAS** (`grnchnas` = the TrueNAS box) — same machine as Immich + the daemon, so the daemon→Gitea push is host-local. | `grnchnas:30008` |

> ⚠️ Immich IP is **`192.191.5.109`** (NOT 192.168.x). The user corrected this once
> already. Don't reintroduce the wrong IP.

> The TrueNAS box is managed **via the web UI only** — the user has **no SSH** to it and
> **no local Docker** on their workstation. That's why the image is built in the cloud
> (GitHub Actions) and pulled by TrueNAS, rather than built locally.

---

## 2. Repos, accounts, paths

**GitHub account:** `grinchdubs`. `gh` CLI is installed and authenticated on the
workstation (SSH protocol). **Note:** the token's scopes are
`admin:public_key, gist, read:org, repo` — it does **NOT** have `packages` scope, so
package-visibility changes must be done in the GitHub web UI or after
`gh auth refresh -s write:packages`.

| Thing | GitHub | Local disk path |
|-------|--------|-----------------|
| **Sync tool** | `github.com/grinchdubs/immich2github` (default branch `main`) | `/home/grnch/Documents/Projects/Github/immich2github/` ← **git root** |
| ↳ actual project subdir | — | `…/immich2github/immich-to-github/` ← **all code lives here** |
| **Photos repo** (originals, by folder) | `grinchdubs/grnch.xyz_photos` | (not checked out locally that we found) |
| **Website** (Jekyll, = grnch.xyz) | `grinchdubs/grinchdubs.github.io` | `/home/grnch/Documents/Projects/Github/grinchdubs.github.io/` |
| **This planning dir** | — | `/home/grnch/Documents/Projects/Github/GiteaRunner/` (has CLAUDE.md, PLAN.md, this file) |
| **AI memory** | — | `/home/grnch/.claude/projects/-home-grnch-Documents-Projects-Github-GiteaRunner/memory/` |
| **Docker image** | `ghcr.io/grinchdubs/immich2github:latest` (**public**, anon-pullable, verified) | — |

> 🪤 **Repo layout landmine:** the git root is `immich2github/`, but the project sits in
> the `immich-to-github/` **subdirectory**. This already bit us once: the CI workflow was
> placed at `immich-to-github/.github/workflows/` and **GitHub never ran it** because
> Actions only reads workflows at the **repo root** `.github/workflows/`. It is now fixed
> (workflow at root, build context points to `./immich-to-github`). Keep this in mind for
> ALL paths.

---

## 3. The sync tool (`immich2github`) — how it works today

Python package. CLI via Click (`python -m src.cli`). Async Immich client (httpx).
Config via Pydantic + a YAML file. Key source files (under `immich-to-github/src/`):

- **`config.py`** — `Config(config_path)` class.
  - Secrets come from **env vars** (via Pydantic `BaseSettings`):
    `IMMICH_API_URL`, `IMMICH_API_KEY`, `GITHUB_TOKEN`.
  - Everything else comes from **`config.yaml`** (see §4).
  - Exposes properties: `github_repo`, `github_branch`, `commit_message_template`,
    `album_mappings`, `tag_mappings`, `exclude_tags`, `allowed_extensions`,
    `max_file_size_mb`, `automation_enabled`, `automation_interval_minutes`,
    `auto_sync_albums`, `auto_sync_tags`, `state_file_path`, `state_backup_enabled`, …
  - 🪤 **`state_file_path` is read ONLY from YAML `state.file_path`.** A `STATE_FILE_PATH`
    env var is **ignored**. State must be on the mounted `/data` volume via YAML.
- **`immich_client.py`** — talks to Immich. `get_albums()`, `get_album_assets(album_id)`,
  `download_asset(id, dir, filename)`, etc. Albums are matched by **NAME** not ID
  (Risograph's id is `a0623c19-…`, but we match the string "Risograph").
- **`github_client.py`** — **THE PART PHASE 1 REPLACES.** Uses **PyGithub** (`from github
  import Github`) and the **GitHub Contents API** (`create_file`/`update_file`). It can
  ONLY talk to github.com — this is the single reason we can't stage to Gitea today.
- **`sync_engine.py`** — orchestrates. `SyncEngine.__init__` builds an Immich client, a
  `GitHubClient(config.github_token, config.github_repo, config.github_branch)`, and a
  `SyncState`. `sync_album(album_name, force)`:
  1. `get_albums()` → find album by name → `get_album_assets(id)`.
  2. filter by extension / `exclude_tags` / already-synced (`state.is_synced(asset.id)`).
  3. for each asset: download to temp dir → size check →
     `github_path = f"{folder}/{asset.original_filename}"` →
     `github_client.upload_file(local_file, github_path, commit_msg, overwrite=force)` →
     `state.mark_synced(...)`.
  4. `state.save_state()` if anything synced.
  - `folder` comes from `album_mappings[album_name]` (Risograph → `risograph`).
- **`state_manager.py`** — `SyncState(path, backup)` JSON tracker: `is_synced(asset_id)`,
  `mark_synced(asset_id, path, checksum, url)`, `save_state()`. This is what prevents
  re-uploading the same photo. It is **independent of the upload backend**, so it keeps
  working after Phase 1.
- **`daemon.py`** — long-running mode. Loop: every `interval_minutes`, call
  `engine.sync_album(name)` for each name in `auto_sync_albums` (and tags for
  `auto_sync_tags`). Prints a startup banner listing albums. The image's default `CMD`
  runs this: `python -m src.cli daemon --config /app/config.yaml`.

### What was already patched (committed, on `main`)
- `daemon.py`: now syncs **albums** (was tags-only); fixed an `asyncio.sleep(1)`
  busy-spin → `time.sleep(1)`; banner lists albums.
- `config.py`: added `auto_sync_albums` property.
- `config.yaml`: created, tracked in git (NOT gitignored), **baked into the image**,
  contains **no secrets**.
- `Dockerfile`: `COPY config.yaml`; `CMD` runs the daemon.
- `.github/workflows/docker-publish.yml`: at **repo root**, builds on push to `main`,
  context `./immich-to-github`, publishes `:latest` + `:<sha>` to ghcr.io. **Build is
  green.** Image is **public**.

---

## 4. Current `config.yaml` (baked into the image, secret-free)

Path: `immich2github/immich-to-github/config.yaml`. Key values:

```yaml
github:
  repo: "grinchdubs/grnch.xyz_photos"   # TODO Phase 2: becomes the Gitea staging repo
  branch: "main"
sync:
  album_mappings: { "Risograph": "risograph" }   # album NAME → folder
  tag_mappings: {}
  exclude_tags: ["private", "draft", "do-not-sync"]
  allowed_extensions: [".jpg", ".jpeg", ".png"]
  max_file_size_mb: 50
automation:
  enabled: true
  interval_minutes: 2                 # poll cadence (Immich has no webhooks)
  auto_sync_albums: ["Risograph"]
  retry_on_failure: true
state:
  file_path: "/data/.sync_state.json" # MUST be on the mounted volume
  backup: true
```

`.env` (gitignored, local only — secrets) holds:
```
IMMICH_API_URL=http://192.191.5.109:30041
IMMICH_API_KEY=<real key>     # currently a PLACEHOLDER
GITHUB_TOKEN=<real PAT>        # currently a PLACEHOLDER
```
On TrueNAS these three are passed as **Custom App env vars**, never baked in.

---

## 5. The plan — phase by phase

### Phase 1 — Convert the upload sink from GitHub-API to plain `git push` ★ENABLER★
This is the linchpin. Once the tool pushes to a *git remote* instead of *github.com
specifically*, "stage locally first" is just "use a different remote URL," and the same
code serves both Gitea (now) and GitHub (later).

**Recommended implementation:**
1. Add `src/git_client.py` with a `GitClient` that mirrors the `GitHubClient` surface
   the engine uses (`upload_file(local_file, repo_path, commit_message, overwrite)` and
   `test_connection()`), but backed by a real git checkout:
   - On init: ensure a working clone exists at e.g. `/data/repo` (clone if missing; else
     `git fetch` + `git reset --hard origin/<branch>`). Set `user.name`/`user.email`.
   - `upload_file`: copy the local file into the clone at `repo_path`, `git add`.
   - Add a `commit_and_push(message)` method; call it **once per sync cycle** (more
     efficient than one commit/push per photo). Before pushing, `git pull --rebase` to
     avoid non-fast-forward rejects if the repo changed elsewhere.
   - Keep returning a URL string for `state.mark_synced(...)` (can be a raw Gitea URL).
2. In `sync_engine.py`, swap `GitHubClient` for `GitClient` (or add a `sink:` selector in
   YAML — `git` vs `github` — if you want both available). Simplest: **replace** it; the
   git sink also works for GitHub later by pointing the remote at github.com.
3. **Config** (new YAML block, secret-free):
   ```yaml
   git:
     remote_host: "grnchnas:30008"          # Gitea on the NAS
     remote_path: "grinchdubs/grnch.xyz_photos.git"
     branch: "main"
     work_dir: "/data/repo"
     author_name: "immich-sync"
     author_email: "immich-sync@grnch.xyz"
   ```
   Inject credentials via **env**, not YAML, to keep config secret-free. **DECIDED: HTTP
   access token.** Read a `GIT_PUSH_TOKEN` env var and build the remote URL at runtime as
   `http://oauth2:${GIT_PUSH_TOKEN}@grnchnas:30008/grinchdubs/grnch.xyz_photos.git`
   (confirm http vs https for the Gitea instance). Don't log the URL with the token in it.
4. **Dockerfile:** ensure **`git` is installed** in the image (python-slim base does NOT
   include it): add `RUN apt-get update && apt-get install -y --no-install-recommends git
   && rm -rf /var/lib/apt/lists/*`. **Easy to forget — the daemon will crash without it.**
5. You can drop the `PyGithub` dependency once `github_client.py` is no longer used.
6. Test locally with `python -m src.cli` against a throwaway Gitea repo before deploying.

> Phase 1 is **independent of the unknowns in §6** — it can be built immediately. The user
> explicitly OK'd starting it.

### Phase 2 — Stand up the staging repo on local Gitea
- Create `grnch.xyz_photos` on the Gitea server (mirror of the GitHub one).
- Create a Gitea **access token** or **SSH deploy key** so the daemon (on TrueNAS) can
  push over the LAN. (Auth method = open question, §6.)
- Point `config.yaml`'s `git:` block + the `GIT_PUSH_TOKEN`/SSH key at this repo.
- The daemon now pushes Risograph originals here. **GitHub is never contacted.**

### Phase 3 — Build the site→photos link + Gitea-runner rebuild → preview on grnchnix:9105
> 🚩 **Important gap:** `grinchdubs.github.io` does **NOT consume the photos yet.** It has
> no `.gitmodules`, no gallery data, and no reference to `grnch.xyz_photos`. The link from
> "photos repo" → "rendered gallery on the site" **must be built here.** This is true
> regardless of staging vs GitHub.

- **Render the gallery:** recommended approach = add the photos repo as a **git submodule**
  at e.g. `assets/photos`, pointed at the **local Gitea** repo for the preview (and at
  GitHub for production later — same mechanism, different remote). Add a Jekyll
  page/layout that loops over `assets/photos/risograph/*` to render the gallery.
  *(User has NOT yet confirmed this approach — see §6.)*
- **Rebuild trigger = the Gitea Actions runner** (this is the agreed job for the
  previously-orphaned runner). Add a Gitea Actions workflow (in the photos repo or the
  site repo) that fires on push and rebuilds the Jekyll preview. This mirrors the GitHub
  Actions pattern you'll use for the public site later.
- **Serve:** `jekyll serve` on grnchnix exposes the result at `:9105`.

### Phase 4 — Validate the full internal loop
Add a photo to Risograph in Immich → within ~2 min daemon pushes to Gitea → runner
rebuilds → photo appears at `grnchnix:9105`. **Zero GitHub involvement.**

### Phase 5 — (DEFERRED) promote to GitHub
Only once the user is happy. Because Phases 1–3 are remote-agnostic, this is a config
change, not a rewrite: point the daemon's git remote (and the site submodule) at GitHub,
or push to both. The public site then rebuilds via GitHub Pages / GitHub Actions.

---

## 6. OPEN QUESTIONS — must get from the user before Phases 2–3

1. ✅ **RESOLVED.** Gitea `host:port` = **`grnchnas:30008`** (Gitea runs on the NAS).
   Auth = **HTTP access token** (Gitea → User Settings → Applications → Generate Token,
   needs repo write). Inject the token as env var **`GIT_PUSH_TOKEN`**; the daemon builds
   the remote as `http://oauth2:${GIT_PUSH_TOKEN}@grnchnas:30008/grinchdubs/grnch.xyz_photos.git`.
   Keep the token OUT of `config.yaml` (env only). *(Note: likely plain `http://`, not
   https — confirm whether Gitea on :30008 has TLS; if not, use `http://`.)*
2. **Gallery rendering approach:** confirm the **git-submodule + Jekyll gallery page**
   plan, or does the user already have a preferred way for photos to display?

(Phase 1 does NOT need these — start there.)

---

## 7. TrueNAS daemon deployment (the part the user says is broken / redo)

Treat as **unverified**. To (re)create cleanly as a **Custom App** in the TrueNAS web UI:

- **Image:** `ghcr.io/grinchdubs/immich2github` **tag** `latest`, pull policy **Always**.
- **Command/Args:** leave empty (image `CMD` already runs the daemon).
- **Env vars:**
  - `IMMICH_API_URL` = `http://192.191.5.109:30041`
  - `IMMICH_API_KEY` = <real Immich key>
  - `GITHUB_TOKEN` = <real PAT>  *(after Phase 1, also/instead `GIT_PUSH_TOKEN` for Gitea)*
- **Storage:** host-path volume → container **`/data`** (e.g. host
  `/mnt/Lepus/apps/immich2github/data`). Holds `.sync_state.json` and the git work-clone.
- **Restart policy:** `unless-stopped`.
- **Networking:** bridge default. **If logs show it can't reach Immich at
  `192.191.5.109:30041`, enable Host Network** — that's the most likely failure mode
  (container can't route to Immich / Gitea on the LAN).

**Debugging a broken daemon:** open the app **Logs** in the TrueNAS UI. Expect a startup
banner listing `Albums: Risograph`. Common failures:
- Missing/placeholder secrets → auth errors against Immich or the git remote.
- Can't reach Immich → connection refused/timeout → Host Network or firewall.
- `git: not found` → the Dockerfile didn't install git (see Phase 1 step 4).
- State not persisting across restarts → `/data` volume not mounted, or `state.file_path`
  not pointing at `/data`.

---

## 8. Decisions LOCKED (do not relitigate)

- **Immich has no webhooks → poll every 2 min.** Not forking Immich. If 2 min ever feels
  slow, drop `interval_minutes` (e.g. to a sub-minute value) — don't fork.
- **grnchnix:9105 = a live Jekyll preview**, on a **separate machine** from TrueNAS.
- **GitHub stays the long-term canonical** host; the local Gitea path is **staging only**.
- **Internal only for now** — do NOT touch GitHub until the internal loop works.
- **The Gitea Actions runner IS used** — for the Phase 3 rebuild (its only job).
- The **immich2github** tool is the canonical implementation. Do **not** rewrite a new
  sync script from scratch (an earlier attempt did that and it was deleted).

## 9. Misc flags / cleanups noticed
- 🔐 The site repo `grinchdubs.github.io` has files named **`github`** and **`github.pub`**
  committed at its root. If `github` is a **private SSH key**, that's a credential leak —
  verify and, if so, purge it from history and rotate the key. (Not part of this task,
  but worth fixing.)
- `gh` token lacks `packages` scope (see §2) — relevant only if you need to script
  ghcr package visibility/deletion.

---

## 10. Suggested first action for the next AI
Start **Phase 1** (git-push sink) — it's unblocked and enables everything else. In
parallel, ask the user the two questions in §6. Do **not** start Phases 2–3 until those
are answered. Keep `config.yaml` **free of secrets** at all times.

# NOTES — verified facts (Phase 0)

Facts confirmed with real API calls before the reconcile rewrite. Do not
re-derive these; re-verify only if the Immich instance changes.

## Immich

- **Version:** 3.0.1 (`GET /api/server/version` → `{major:3, minor:0, patch:1}`).
  The Workflows feature exists in 3.0.0+; not yet inventoried (see Open items).
- **Target album:** `Risograph`, id `a0623c19-3f33-4ddd-ac16-3fa873d3592a`,
  `assetCount` 125, `order: "desc"`.
- **Album detail does NOT embed assets:** `GET /api/albums/{id}` returns
  `assetCount` but an empty `assets` array in v3. Asset lists come from
  `POST /api/search/metadata` with `{"albumIds":[id], "page", "size"}`.
- **Ordering is date-based, not manual drag.** The album carries `order`
  = `"asc"|"desc"`; there is no per-asset manual position in the API. We
  replicate the UI order by sorting assets on `fileCreatedAt` in that
  direction. (If manual album ordering is ever exposed, revisit this.)
- **Search items include:** `id`, `checksum`, `fileCreatedAt`, `updatedAt`,
  `originalFileName`, `type`, dimensions. They do **not** include the caption.
- **Captions live in `exifInfo.description`,** fetched per-asset via
  `GET /api/assets/{id}` (search results trim exifInfo). Sampled asset had an
  empty description — no captions are set on the album yet.
- **A description edit does NOT bump `updatedAt`** (verified: PUT
  `/api/assets/{id}` `{"description":...}` changed the caption but left
  `updatedAt` byte-identical, in both the per-asset and search responses). Since
  the bulk search API also omits descriptions, there is **no cheap change signal
  for captions** — the reconcile engine fetches every asset's description each
  run and compares it to the manifest. (Checksum caching still works: bytes
  don't change silently, and `checksum` comes from the bulk search.)
- **Checksum = `base64(sha1(original bytes))`** — verified byte-for-byte
  against a downloaded original. Lets us match existing repo files to album
  assets by content, so the migration to ordered filenames renames in place
  instead of re-downloading.

## Reconcile model (implemented)

- The Immich album is the source of truth. Every run reconciles the photos
  repo to match it: add new, delete removed, rename on reorder. Idempotent.
- Files are named `NNN_originalname.ext` (`NNN` = zero-padded album position),
  so ordering survives in plain git and reorders appear as renames in the diff.
- Each folder gets an `index.json` manifest: ordered `{position, file,
  immich_id, checksum, caption}`, plus a top-level `generated_at`. It drives the
  site gallery (order + captions); `checksum` doubles as a cache so unchanged
  assets skip a local checksum re-read. `generated_at` is held stable when the
  desired state is unchanged so a no-op run yields byte-identical JSON (else a
  fresh timestamp every cycle would push empty commits forever).
- No incremental sync state (`synced_assets.json` is gone). The repo working
  tree + the manifest are the only state, and both are re-derivable.
- **Validated end-to-end** against real Immich (local bare-repo push target):
  initial add, idempotent no-op (no commit), reorder→renames w/ no re-download,
  caption edit→recaption, stray-file removal, and append-era→ordered migration
  (renames, zero downloads). All green.

## Git path

- Push works over `grnchnas:30008`; `fetch`/`clone` (upload-pack) black-holes
  through the container's Tailscale route (1280 MTU). The daemon is push-only
  and never fetches, so it is unaffected. Anything that must *clone* (a future
  Gitea Actions runner) must use the LAN IP `192.191.5.109:30008`.

## Open items (not blocking the sync core)

- **Immich Workflows inventory** (Phase 2 Option A): needs the web UI JSON
  schema view; not done. The poll/cron reconcile is the backbone regardless,
  so the webhook is a later optimization.
- **Gitea `workflow_dispatch`** (Phase 4 promote job): not tested. Promotion to
  GitHub is deferred and must be fast-forward only (never force-push GitHub —
  the live site hotlinks its raw URLs).

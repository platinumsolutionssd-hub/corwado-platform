# CORWADO Agricultural Extension & Market Linkage Platform — v0.1

Prototype backend for ToR-001-06-2026, built against the Unified Platform
Architecture doc (Ngong Gold + CORWADO shared core).

## Status (Day 15 — real database verification, 2026-07-11)

**The Day 15 milestone below ("end-to-end rehearsal against a real
database") is now genuinely done for the backend/agri-venture-v2
integration path** — not the full breadth of that original bullet
(aggregation events, buyer matching, radio dispatch, and `npm run dev`
on the frontend are still unverified against a real DB; scope was the
new BiophysicalEngine/parcel_crop_baseline work specifically). This
replaces every prior "should work, not run here" caveat for that path
with an actual result.

**Real PostgreSQL 17 + PostGIS 3.6 were installed and run** — no admin
rights, no Docker: EDB's portable zip binaries + the OSGeo PostGIS
bundle, extracted and started as a plain user process (`initdb` + a
non-service `postgres` on a local port). `db/schema.sql` ran clean
against it, first time ever, with no errors — including the
`parcel_crop_baseline` migration (see below) and its `DROP COLUMN`
statements. The real, live `uvicorn app.main:app` (not a mocked
function call) was then run against this database and against the
actual running agri-venture-v2 service over HTTP.

**BiophysicalEngine now makes a real HTTP call** to agri-venture-v2's
`/analyze` (base URL from `AGRIVENTURE_API_URL`, env-var pattern
matching `DATABASE_URL`), replacing the old fixed-number stub. Its
response is mapped into two parts, stored in a new `parcel_crop_baseline`
table (replacing the old single `parcel.baseline_suitability` JSONB
column, which had no FK integrity to `crop_dictionary_entry` and
couldn't track staleness per crop): a flattened summary
(`overall_score`, `overall_classification`, `is_fatal`,
`binding_domain`, `confidence`) for cheap dashboard reads, and the full,
unmodified `AnalysisResult` tree alongside it — every
`DomainResult`/`FactorScore`/`Evidence`, never discarded, per
agri-venture-v2's own Explainability Requirement.

**Three real bugs surfaced by actually running this against Postgres**
(none of them were catchable by syntax checks or mocked tests):

1. `radio_station.payam_coverage` was `Column(JSON)` in `app/models.py`
   but `TEXT[]` in `db/schema.sql` — Postgres rejected every insert
   outright, so `app/seed.py` failed completely, not just for radio
   data. **Fixed** — now `Column(ARRAY(Text))`, matching the real schema.
   Confirmed by re-running `app/seed.py` end-to-end: cooperative,
   5 demo stewards, radio station + slot, and crop dictionary entries
   all committed for real.
2. `Parcel.area_acres` was `Column(Numeric, nullable=True)` with a
   comment claiming it was "read-only" — but nothing enforced that;
   SQLAlchemy put `area_acres = NULL` in every `INSERT`, which Postgres
   rejects for a `GENERATED ALWAYS ... STORED` column. **Fixed** —
   `server_default=FetchedValue()` tells SQLAlchemy to omit it from
   INSERT/UPDATE and fetch the server-computed value back instead.
3. `get_baseline()`'s staleness check compared naive
   `datetime.utcnow()` against `refresh_due`/`computed_at`
   (`DateTime(timezone=True)` columns — Postgres/psycopg2 return
   timezone-aware values), raising `TypeError` on the *cached*-baseline
   code path. Only surfaced once a real Postgres row was read back on a
   second request — no mock reproduces real tzinfo. **Fixed** — uses
   `datetime.now(timezone.utc)` throughout.

**Four checks passed against the live endpoint after those fixes**
(real Kibiko parcel — the actual `KIBIKO_PARCEL` coords from
agri-venture-v2's `providers/gee_fetch.py` — registered via the real
`POST /api/parcels`):

| Check | Result |
|---|---|
| maize @ Kibiko, first call | `200`, ~12s, `S2` / `0.6153` / binding domain `climate` / not fatal / confidence `low` — temperature-bound at ~2000m altitude, clean soil (pH/clay/depth all S1); persisted correctly in `parcel_crop_baseline` |
| maize @ Kibiko, second call | `200`, fast, `cached: true` — real staleness check against real Postgres timestamps |
| `crop=sorghum` (not in `crop_dictionary_entry`) | `404` — never reached agri-venture-v2 |
| `UNIQUE(parcel_id, crop_id)` | Direct duplicate insert via `psql` → real rejection: `duplicate key value violates unique constraint` |
| agri-venture-v2 unreachable | `503` with the real connection error, in ~2s, via a second CORWADO instance pointed at a dead port — confirmed no partial write to the existing cached row |

## Status (post-Day 14, updated after architecture review)

**Two small changes applied following an external architecture review**
(full reasoning recorded in the architecture doc's v0.2 addendum —
adopted 2 of 7 suggestions, declined the rest as premature for this
project's actual scale):

1. **Renamed `digital_twin_score()` → `BiophysicalEngine.analyse()`.**
   "Digital Twin" implies continuous sensor sync to a live physical
   asset; what this does is a batch/on-demand suitability score. Only
   the Python name changed — the database enum value `'digital_twin'`
   (in `advisory_source`) was deliberately left as-is, since renaming a
   stored enum value is a schema decision, not a naming cleanup, and
   wasn't part of what was agreed.
2. **Added `app/services/advisory_engine.py`** — a lightweight
   `AdvisoryEngine` Protocol. With two real implementations
   (`BiophysicalEngine`, `SatyuktSat2FarmEngine`) now sharing one output
   shape, this abstraction is earned, not speculative — it's what makes
   adding a third engine (agri-venture-v2, once integrated) a clean
   addition rather than a special case. Deliberately does NOT include a
   registry, factory, or dynamic-loading mechanism — those were
   explicitly declined in the architecture review as premature for two
   engines; revisit only when a third real one needs it.

**Everything else is unchanged from Day 14** — full detail below.

### Days 12-14 detail (prior, unchanged by the review)

**Working now, in addition to Days 1-11:**
- **`frontend/` — real React source code that calls the live API.** Not
  the standalone demo with seed data anymore: `frontend/src/api.js` is
  a genuine fetch client against every backend endpoint built Days 1-11,
  and `frontend/src/App.jsx` uses it with honest loading and error
  states (a failed fetch shows a retry banner, not silently empty data).
  **Important limitation:** this only works once the FastAPI backend is
  actually deployed and reachable — set `VITE_API_URL` in a `.env` file
  (copy `.env.example`) to point at it. It cannot run inside Claude's
  sandboxed artifact preview, which has no way to reach an undeployed
  backend — that's why the interactive demo (`corwado-platform-demo.jsx`,
  presented separately) still exists and still uses seed data. They
  serve different purposes: the demo is clickable today, the frontend
  folder is what you'll actually deploy.
- **Accessibility commitments from `docs/ACCESSIBILITY.md` implemented
  in code, in both the demo and the real frontend:** visible keyboard
  focus on every interactive element, `prefers-reduced-motion` respected,
  skip-to-content link, semantic `<header>`/`<nav>`/`<main>`/`<h2>`
  instead of styled `<div>`s, `aria-hidden` on decorative icons,
  `aria-label`/`aria-current`/`aria-modal` where needed, and — the
  specific commitment from that doc — severity is now shown with an
  explicit text label ("Attention" / "OK") next to the icon and color,
  not icon-and-color alone.

**Honesty note on testing:** this sandbox has no internet access, so I
could not install React/Vite/npm packages to actually run or build the
frontend. `npm run dev` from a fresh `npm install` was not tested here.
I did: validate `package.json` as JSON, run `node --check` on the
non-JSX files, and manually trace every JSX tag in both `App.jsx` files
for balance and correct nesting — that catches structural errors but
not, for example, a typo'd prop name. Test `npm install && npm run dev`
locally before relying on this for a live demo.

**Stubbed, honestly:** unchanged from Day 11.

## Local setup (once you have Postgres+PostGIS available)

```bash
# 1. Create the database and load the schema
createdb corwado_platform
psql corwado_platform -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql corwado_platform -f db/schema.sql

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your connection string
export DATABASE_URL="postgresql://user:pass@localhost:5432/corwado_platform"

# 4. (Optional) load demo data
python -m app.seed

# 5. Run
uvicorn app.main:app --reload
```

Visit `http://localhost:8000/docs` for interactive API docs (auto-generated
by FastAPI/Swagger).

### External dependency: agri-venture-v2 (required for advisory/suitability)

`BiophysicalEngine` (see `app/routers/advisory.py`) calls out to a separate
sibling project, `agri-venture-v2`, over HTTP for real crop-suitability
scoring (`AGRIVENTURE_API_URL`, default `http://localhost:8000`) — this is
why the CORWADO backend itself is normally run on **port 8001** instead of
FastAPI's default 8000, to avoid colliding with it. Any farmer-facing
suitability/baseline check (`GET /api/advisory/parcel/{parcel_id}/baseline`
and friends) will fail with `agri-venture-v2 unreachable at
http://localhost:8000/...` until that service is also running.

To start it (from the `agri-venture-v2/backend/` directory, a separate repo
on disk, not part of this one):

```bash
python -m uvicorn server:app --reload --port 8000
```

It calls Google Earth Engine directly for real climate/soil observations, so
it needs `ee.Authenticate()` already set up locally against the GEE project
hardcoded in its `providers/gee_fetch.py` — see that project's own
`CLAUDE.md` for details. It also uses `--reload`, so it's subject to the
exact same orphaned-worker restart risk described below.

## Troubleshooting / known gaps

**`uvicorn --reload` restarts can silently hit a stale, orphaned process
(confirmed on this Windows dev machine, 2026-07-13).** `--reload` runs two
processes: a supervisor (the one with `uvicorn` in its command line) and a
worker it spawns via `multiprocessing.spawn_main` to actually run the app —
that worker's command line has no `uvicorn` substring in it at all. Killing
only the supervisor (e.g. `Stop-Process` on whatever PID has "uvicorn" in
its name, or closing that terminal window) does not kill the worker: it's
reparented, keeps holding the listening port, and keeps running with
whatever environment variables (`TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, etc.)
it had at its *original* spawn time. Every request after that "restart"
keeps hitting the same stale worker — changing env vars or code and
restarting appears to do nothing, because nothing was actually restarted.
In one debugging session this produced four stacked orphans in a row, each
started specifically to pick up a newly-set `TELEGRAM_BOT_TOKEN`, none of
which ever did.

Fix — before starting a fresh backend, kill the *entire* process tree, not
just the PID with "uvicorn" in it, and confirm the port is actually free
before relaunching:

```powershell
# Kill supervisor + worker together (taskkill /T recurses to children)
taskkill /PID <supervisor_pid> /T /F

# Confirm nothing is still bound to the port before restarting
Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
```

If that still shows an owner, find it directly rather than guessing by
command-line substring — the orphaned worker's `CommandLine` looks like
`python.exe "-c" "from multiprocessing.spawn import spawn_main; ..."
"--multiprocessing-fork"`, with no mention of uvicorn:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Select-Object ProcessId,ParentProcessId,CommandLine
```

## Note on this sandbox

This code was written in an environment with no internet/database access,
so it hasn't been run end-to-end here. Syntax and logic have been reviewed
carefully, but test it locally before relying on it for a live demo.

## Next in the 15-day plan

- ~~Days 2–3: wire routers to real SQLAlchemy/PostGIS~~ — done
- ~~Days 4–6: message dispatch logic~~ — done (Day 4)
- ~~Days 7–9: market linkage matching + notifications~~ — done
- ~~Days 10–11: radio-channel + accessibility design closure~~ — done
- ~~Days 12–14: real frontend wired to the live API + accessibility
  implementation~~ — done
- ~~Day 15 (final), backend/agri-venture-v2 path: end-to-end rehearsal
  against a real database~~ — done 2026-07-11, see "Status (Day 15 —
  real database verification)" above. `psql -f db/schema.sql`,
  `python -m app.seed`, and `uvicorn app.main:app` all actually ran
  against real PostgreSQL 17 + PostGIS 3.6, and three real bugs it
  surfaced are fixed. **Still open, not covered by that run:** `npm run
  dev` on the frontend, and clicking through the other workflows this
  bullet originally scoped — create an aggregation event, confirm a
  buyer match, trigger a radio broadcast. Those still need their own
  real-infrastructure rehearsal before Day 15 is fully closed out.

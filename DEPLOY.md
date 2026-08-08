# Deploying CORWADO to Render

CORWADO is a **third** service on top of the two in agri-venture-v2's own
DEPLOY.md (its backend + the farmlab frontend). It does not redeploy those
— it *depends* on the agri-venture-v2 backend already being live, reached
over HTTP for every crop-suitability baseline.

| Part | Render type | Tier |
|---|---|---|
| CORWADO backend (FastAPI + Telegram webhook) | Web Service | **Starter ($7/mo) — see §6** |
| CORWADO frontend (Vite) | Static Site | free |
| PostgreSQL + PostGIS | Render Postgres | free (time-limited instance) |

There is **no separate Telegram process** — inbound Telegram is a webhook
served by the backend Web Service itself (§6), not a poller.

---

## 1. GitHub

CORWADO is already a git repo. Before pushing, eyeball `git status` — make
sure no `.env` or bot token is staged (`.gitignore` should already exclude
them). Then commit and push to its GitHub repo.

---

## 2. Render — PostgreSQL

Create a Render **PostgreSQL** instance. Note its connection URL. Render
hands out a `postgres://…` URL — SQLAlchemy 2.0 rejects that scheme; rewrite
the prefix to `postgresql://…` before using it as `DATABASE_URL`.

Load schema + seed (run locally against the DB's **external** URL):
```
psql "postgresql://…render-external-url…" -f db/schema.sql
DATABASE_URL="postgresql://…" python -m app.seed
psql "postgresql://…render-external-url…" -f db/migrations/001_multitenancy.sql
```
`001_multitenancy.sql` adds organizations + Row-Level Security tenant
isolation, and backfills all existing rows to the CORWADO org. Run it **after**
schema + seed. RLS binds only because the migration sets `FORCE ROW LEVEL
SECURITY` (so the table-owning app role is subject to it) — do **not** run the
app as a Postgres superuser or a role with `BYPASSRLS`, or isolation is silently
void. Render's default database role is a non-superuser owner, which is correct.
`db/schema.sql` enables `postgis` + `uuid-ossp` itself. The seed run is
idempotent and is what registers all crops — including cassava/soybean's
real agri-venture-v2 scoring keys.

---

## 3. Render — CORWADO Backend Web Service

- Root directory: (repo root)
- Environment: Python 3
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/api/health`
- Instance type: **Starter** (see §6 for why not free)

**Environment variables:**
| Name | Value is... |
|---|---|
| `DATABASE_URL` | Render Postgres **internal** URL, rewritten to the `postgresql://` scheme. |
| `JWT_SECRET` | Long random secret (>=32 bytes) that signs staff/landlord auth tokens. **No default — the app fails to start if unset** (fail-closed, by design; see `app/security.py`). Generate once with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and keep it stable (rotating it invalidates all existing logins). |
| `AGRIVENTURE_API_URL` | `https://agri-venture-backend.onrender.com` (NO trailing slash). Without this it defaults to `localhost:8000` and every baseline fails. |
| `TELEGRAM_BOT_TOKEN` | Your production bot token (outbound replies/dispatch + used by `set_webhook`). |
| `TELEGRAM_WEBHOOK_SECRET` | Any long random string. The webhook endpoint 403s every update unless this is set here **and** matches what `set_webhook` registered (§6). |
| `FRONTEND_BASE_URL` | The frontend's Render URL from §4 (set after that exists). |

`RENDER_EXTERNAL_URL` is injected automatically by Render — `set_webhook`
reads it, so you don't set it yourself.

---

## 4. Render — CORWADO Frontend Static Site

- Build command: `npm install && npm run build`
- Publish directory: `dist`
- Env var `VITE_API_URL` = the backend Web Service URL from §3 (no trailing
  slash). The frontend's built-in fallback is `:8000` (agri-venture's port),
  so this MUST be set or the UI hits the wrong service. Vite bakes it in at
  build time — changing it needs a rebuild, not just a restart.

---

## 5. Close the loop — CORS

`app/main.py` currently allows all origins (`["*"]`). Tighten to the
frontend's real Render URL before real use.

---

## 6. Telegram webhook — register once, and why Starter tier

Inbound Telegram arrives as a webhook the backend already serves at
`/api/telegram/webhook`. After the backend is deployed (§3, with
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` set), register it **once**:

```
# From the Render backend shell, or any machine with the same
# TELEGRAM_BOT_TOKEN + TELEGRAM_WEBHOOK_SECRET set and the deployed URL:
python -m app.set_webhook            # uses $RENDER_EXTERNAL_URL on Render
# or, off-Render:
python -m app.set_webhook --url https://<your-backend>.onrender.com
```
It prints `getWebhookInfo` — confirm `url` is the deployed
`/api/telegram/webhook` and `last_error_message` is absent. Re-run only if
the service URL changes (stable across normal redeploys) or the token
rotates. `python -m app.set_webhook --delete` deregisters.

**Only one webhook (or poller) per bot token** — Telegram 409s the rest.
Don't run a local poller/webhook against the production token; use a
separate dev bot for local testing (see STARTUP.md §5).

**Why the backend runs on Starter ($7/mo), not free:** Render's free tier
spins a Web Service down after ~15 min idle. The webhook itself works on any
tier, but on free tier the first message after each idle period pays a
10–30s cold start (container boot + imports + first DB connect). In a
low-traffic pilot where farmers message sporadically, *most* messages would
hit that — a genuinely bad experience for real users (registration, price
checks). Starter removes spin-down entirely: always warm, instant webhook
responses, healthy Telegram delivery, plus RAM/CPU headroom. For ~two
coffees a month that's the right call for a pilot with real users. (A pure
demo can stay free + an external `/api/health` pinger every ~10 min to mask
spin-down — a hack, not a guarantee, and not for anything users depend on.)

This tier decision is **specific to CORWADO's backend**. agri-venture-v2's
own tier is a separate call on its own merits: CORWADO's chat path is
cached-only (never triggers a live agri-venture call), so agri-venture's
cold start only affects its own dashboard's live analyze, not the bot.

---

## First-request warm-up caveat

Any service still on Render's free tier spins down when idle. The first
request after idleness cold-starts it (and, for a live dashboard analyze,
the agri-venture-v2 backend it calls — which also inits Earth Engine).
Expect that first hit to be slow. On the Starter-tier CORWADO backend this
doesn't apply; it stays warm.

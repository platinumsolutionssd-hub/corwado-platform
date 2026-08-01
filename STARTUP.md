# CORWADO Platform — Startup Reference

Four core processes, four separate terminal windows. Each one stays open
and running — don't close a window once its process has started. A fifth
process (an ngrok tunnel) is only needed when you want to test the Telegram
bot end-to-end locally — see §5; day-to-day dashboard work doesn't need it.

Keep this file in `corwado-platform/` (e.g. `STARTUP.md`) for reuse.

**Updated** after real usage revealed two things in the original version
were wrong: the database connection details, and a missing `python -m`
prefix on the agri-venture-v2 command. Both fixed below.

---

## The five processes, in start order

| # | What | Port | Terminal command |
|---|---|---|---|
| 1 | PostgreSQL | 5432 | Usually already running — see check below |
| 2 | agri-venture-v2 backend | 8000 | see below |
| 3 | CORWADO backend | 8001 | see below |
| 4 | CORWADO frontend | 5173/5174/5175 (Vite picks one free) | see below |
| 5 | ngrok tunnel (Telegram bot testing only — optional) | — (public HTTPS → 8001) | see §5 |

Start in this order — CORWADO's backend depends on both Postgres and
agri-venture-v2 being up first, and the frontend depends on CORWADO's
backend.

---

## Step 0 — Clean slate (do this first if anything's acted strange before)

```
Get-Process python | Stop-Process -Force
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
```

Kills every Python and Node process on the machine. Safe — everything
below gets restarted anyway. Worth doing whenever something's behaving
oddly (stale env vars, port conflicts, orphaned workers) rather than
guessing which process is the problem.

---

## 1. PostgreSQL (port 5432)

Check if it's already running:
```
netstat -ano | findstr :5432
```
A line containing `LISTENING` means it's up — nothing to do.

If nothing shows up, it needs restarting from the portable install.
Ask Claude Code for the exact path if you don't have it noted — it was
set up under a `scratchpad` folder during initial setup, not a normal
install location.

**Real connection details, confirmed correct as of the most recent
sessions** (the original version of this file had the wrong ones —
an earlier port-5433/corwado_admin setup that was since superseded):
- Host/port: `localhost:5432`
- User: `corwado_user`
- Password: `changeme`
- Database: `corwado_platform`
- Full connection string:
  `postgresql://corwado_user:changeme@localhost:5432/corwado_platform`

This is CORWADO's own app default (`app/database.py`) — you generally
don't need to set `DATABASE_URL` explicitly at all unless something's
overriding it, but it's included below for clarity/reliability.

---

## 2. agri-venture-v2 backend (port 8000)

New terminal:
```
cd Desktop\agri-venture-v2\backend
python -m uvicorn server:app --reload --port 8000
```
(`python -m` matters — a bare `uvicorn` command frequently isn't on a
fresh terminal's PATH and fails with "not recognized.")

Wait for: `Uvicorn running on http://127.0.0.1:8000` and
`Earth Engine initialised. Agri-Venture v2 server ready.`

---

## 3. CORWADO backend (port 8001)

New terminal:
```
cd Desktop\corwado-platform
$env:TELEGRAM_BOT_TOKEN="<paste your ACTUAL current bot token here — do not leave the angle brackets or this placeholder text in place>"
$env:DATABASE_URL="postgresql://corwado_user:changeme@localhost:5432/corwado_platform"
python -m uvicorn app.main:app --reload --port 8001
```
`TELEGRAM_BOT_TOKEN` powers outbound replies/dispatch. For **inbound**
Telegram (testing the bot locally, §5) also set
`$env:TELEGRAM_WEBHOOK_SECRET="<any random string>"` here — it must match
the value you pass to `set_webhook`, or `/api/telegram/webhook` 403s every
update. Neither is needed for dashboard-only work.
Wait for: `Uvicorn running on http://127.0.0.1:8001` **and**
`Application startup complete`

**Known issue (found and fixed once already):** `--reload` spawns a
separate worker process. If you ever kill this terminal by closing the
window instead of Ctrl+C, the worker can survive as an orphan holding
port 8001 with a stale/missing environment — the next "fresh" start
then silently fails against that ghost, not the real one. If restarts
stop working for no visible reason, run Step 0's cleanup first.

---

## 4. CORWADO frontend

New terminal:
```
cd Desktop\corwado-platform\frontend
npm run dev
```
Wait for a line like:
```
➜  Local:   http://localhost:5173/
```

**The port is NOT always 5173.** Vite tries 5173 first, but if that
port is already in use by something else (a leftover process, another
app), it automatically moves on to 5174, 5175, etc. **Always use
whatever port the terminal actually prints**, not a number from memory
or from a previous session — this has genuinely changed session to
session before. If you go to `localhost:5173` and it says the site
isn't running, check this terminal's output for the real port first,
before assuming something's broken.

Confirm `.env` in this folder has `VITE_API_URL=http://localhost:8001`
if you ever see a "Failed to fetch" error once the page does load.

---

## 5. Telegram bot — webhook model (local testing is optional)

**The long-polling poller has been retired.** Inbound Telegram now arrives
as a webhook: Telegram POSTs each update to `/api/telegram/webhook` on the
CORWADO backend (process #3), which is served by the same uvicorn — there
is **no separate bot process to run** anymore. In production the webhook is
registered once with `python -m app.set_webhook` (see DEPLOY.md).

Locally the backend has no public HTTPS URL, so Telegram can't reach it
directly. To test the bot end-to-end on your machine you need a tunnel and,
critically, a **separate DEV bot token** — never the production token.

> **Why a dev token, non-negotiable:** a webhook and `getUpdates()` are
> mutually exclusive per token, and only one webhook URL exists per token
> at a time. Pointing a local ngrok webhook at the **production** bot token
> would silently hijack production's webhook (every farmer's message would
> start hitting your laptop). Use a second bot from @BotFather for local
> testing.

If you just want the dashboard, skip this whole step — only the Telegram
bot path needs it.

**a. Start a tunnel to the CORWADO backend (port 8001):**
```
ngrok http 8001
```
Note the `https://<random>.ngrok-free.app` URL it prints.

**b. Point the DEV bot's webhook at the tunnel** (new terminal):
```
cd Desktop\corwado-platform
$env:TELEGRAM_BOT_TOKEN="<your DEV bot token — NOT production>"
$env:TELEGRAM_WEBHOOK_SECRET="<any random string; must match the backend's>"
python -m app.set_webhook --url https://<random>.ngrok-free.app
```
The backend (process #3) must have been started with the **same**
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` set, or its
`/api/telegram/webhook` will 403 every update. `set_webhook` prints
`getWebhookInfo` at the end — confirm `url` is your ngrok URL and
`last_error_message` is absent.

**c. Message the DEV bot** and watch the process-#3 terminal for the
inbound request. Replies come back through the same bot.

**To revert to no webhook** (e.g. before switching that token elsewhere):
```
python -m app.set_webhook --delete
```

**Common failures:**
- **Every update 403s in the backend log** → the backend and `set_webhook`
  were run with different `TELEGRAM_WEBHOOK_SECRET` values (or the backend
  has none set). They must match exactly.
- **`getWebhookInfo` shows a `last_error_message` about connection/HTTPS**
  → ngrok isn't running, or the `--url` was wrong. Restart ngrok and re-run
  `set_webhook` with the current URL (ngrok's free URL changes each run).
- **`404 Client Error` from `set_webhook`** → the bot token is wrong, most
  often literal placeholder text (`<your ... token>`) typed in instead of
  the real value.

---

## Verify everything's actually up

```
curl http://localhost:8000/docs
curl http://localhost:8001/api/health
```
The second should return:
`{"status":"ok","platform":"CORWADO LAST Project — ToR-001-06-2026"}`

Then open the frontend in your browser and confirm the dashboard shows
real farmer data, not an error banner.

---

## Common gotchas, worth remembering

- **Environment variables don't persist between terminal windows.**
  Every fresh terminal running `uvicorn`, `set_webhook`, or a dispatch
  needs `$env:TELEGRAM_BOT_TOKEN=...` (and, for the bot webhook,
  `$env:TELEGRAM_WEBHOOK_SECRET=...`) set again, every time.
- **Check before you restart, don't assume.** `Get-Process python`
  first, so you know exactly what's already running before adding
  more to the pile.
- **A python.exe process existing doesn't mean it's the right one, or
  healthy.** Confirm with `curl` against the actual endpoint before
  trusting it.
- **Never type placeholder/example text literally** — anything shown
  in angle brackets like `<your token>` is meant to be replaced
  entirely with a real value, not copied as-is.

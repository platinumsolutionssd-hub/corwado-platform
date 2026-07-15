"""
Telegram inbound poller — LOCAL DEVELOPMENT ONLY.

Polls Telegram's getUpdates() endpoint instead of registering a webhook,
because a webhook needs a public HTTPS URL this local dev environment
doesn't have. A real deployment would switch to a webhook once a real
public URL exists; nothing here should be mistaken for that.

Runs as its own process, separate from `uvicorn app.main:app --reload`
— same pattern as Postgres and agri-venture-v2, both reached over
DB/HTTP rather than embedded in the FastAPI app. Kept out-of-process
specifically because uvicorn --reload restarts its worker on every file
save, which would flap or double-run an in-process polling loop.

last_update_id is held in memory only, not persisted — every intent
this bot supports (REGISTER, PRICE, STATUS) is safe to re-process, so a
restarted poller re-handling a small backlog costs nothing. A real
webhook deployment doesn't have this problem at all, since Telegram
pushes each update exactly once.

Run with:
    python -m app.telegram_poller
Requires TELEGRAM_BOT_TOKEN in the environment.
"""
import os
import time

import requests

from app.database import SessionLocal
from app.services import telegram_inbound

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
LONG_POLL_TIMEOUT_SECONDS = 25
ERROR_BACKOFF_SECONDS = 3


def _get_updates(offset):
    resp = requests.get(
        f"{API_BASE}/getUpdates",
        params={"offset": offset, "timeout": LONG_POLL_TIMEOUT_SECONDS},
        timeout=LONG_POLL_TIMEOUT_SECONDS + 10,
    )
    resp.raise_for_status()
    return resp.json()["result"]


def _send_message(chat_id, text):
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    resp.raise_for_status()


def run():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set — see README for local setup")

    print("Telegram poller started (local-dev polling mode, no webhook).")
    last_update_id = None
    while True:
        try:
            offset = last_update_id + 1 if last_update_id is not None else None
            updates = _get_updates(offset)
            for update in updates:
                last_update_id = update["update_id"]
                message = update.get("message")
                if not message or "text" not in message:
                    continue
                chat_id = message["chat"]["id"]
                db = SessionLocal()
                try:
                    reply = telegram_inbound.handle_update(db, update)
                except Exception as e:
                    # One bad message must not take the whole poller down --
                    # confirmed live 2026-07-14: an uncaught UniqueViolation
                    # inside handle_update() (a REGISTER conflict case it
                    # didn't itself guard against) propagated all the way up
                    # through this loop and killed the process outright,
                    # leaving the bot unresponsive until manually restarted.
                    # last_update_id is already advanced above, so this
                    # update is skipped rather than retried forever.
                    print(f"[{chat_id}] error processing update, skipping: {e!r}")
                    continue
                finally:
                    db.close()
                if reply:
                    _send_message(chat_id, reply)
                    print(f"[{chat_id}] {message['text']!r} -> {reply!r}")
        except requests.RequestException as e:
            print(f"Telegram API error, retrying in {ERROR_BACKOFF_SECONDS}s: {e}")
            time.sleep(ERROR_BACKOFF_SECONDS)


if __name__ == "__main__":
    run()

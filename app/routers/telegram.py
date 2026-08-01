"""
Telegram webhook router — the production inbound transport, replacing
app/telegram_poller.py's local-dev long-polling entirely.

Telegram POSTs one Update object per event to this endpoint (unlike
getUpdates, which returned a batch). The message-handling logic is NOT
here: it lives in app/services/telegram_inbound.handle_update(), exactly
as it did for the poller — this router is a thin HTTP transport around
that same shared core, and app/services/telegram_sender.send() does the
outbound reply. Retiring the poller removed only its polling loop; the
handler and sender it called are reused verbatim.

Security: this endpoint is public, so every request is authenticated by
the secret Telegram echoes back in the X-Telegram-Bot-Api-Secret-Token
header (set via setWebhook's secret_token param — see app/set_webhook.py).
A missing or wrong secret is a 403; nothing else can inject fake updates.

Response contract: ALWAYS HTTP 200 once authenticated, even when handling
raises. A 5xx would make Telegram retry on a backoff and can eventually
throttle delivery — so a bad single update is contained and logged here,
never propagated, matching the poller's own per-update skip-and-continue
behavior (same at-most-once semantics, not a regression). No BackgroundTask
offload: the inbound chat path is cached-only by design (see
telegram_inbound._handle_farmlab's docstring — it never makes a live
agri-venture-v2 call), so handling is sub-second and inline is fine. If a
slow handler is ever added, revisit with a BackgroundTask + its own DB
session then, not pre-emptively.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import telegram_inbound, telegram_sender

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared secret round-tripped through Telegram's setWebhook secret_token.
# No localhost-style default on purpose — unlike DATABASE_URL /
# AGRIVENTURE_API_URL, a blank webhook secret is a security hole, not a dev
# convenience, so an unset value must fail closed (every request 403s)
# rather than silently accept anything. app/set_webhook.py reads the same
# env var so the value registered with Telegram and the value checked here
# are guaranteed to be one source.
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")


@router.post("/webhook")
def telegram_webhook(update: dict, request: Request, db: Session = Depends(get_db)):
    """
    Receives one Telegram Update, authenticates it via the secret-token
    header, and delegates to the same handle_update()/send() pair the
    poller used. Returns {"ok": true} with HTTP 200 in every authenticated
    case (see module docstring on why errors never become a 5xx here).
    """
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not TELEGRAM_WEBHOOK_SECRET or supplied != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="invalid webhook secret")

    try:
        reply = telegram_inbound.handle_update(db, update)
        if reply:
            # chat.id is guaranteed present whenever handle_update returned a
            # non-empty reply: it only does so after its own
            # `if not message or "text" not in message: return ""` guard,
            # having already read message["chat"]["id"] itself.
            chat_id = str(update["message"]["chat"]["id"])
            ok, detail = telegram_sender.send(chat_id, reply)
            if not ok:
                logger.warning("Telegram send failed for chat %s: %s", chat_id, detail)
    except Exception:
        # Contain, don't propagate — see the module docstring's 200 contract.
        logger.exception("error handling Telegram update")

    return {"ok": True}

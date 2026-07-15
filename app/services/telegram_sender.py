"""
Telegram outbound sending — the real Bot API call behind dispatch_to_
steward()'s 'telegram' channel. Same sendMessage endpoint
app/telegram_poller.py uses for inbound replies, but usable as a
standalone sender for outbound dispatch (price alerts, advisory
notices) rather than only in response to an inbound message.
"""
import os

import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE = "https://api.telegram.org/bot{token}"


def send(chat_id: str, text: str) -> tuple[bool, str]:
    """
    Sends text to chat_id via the real Telegram Bot API.

    Returns (success, detail): detail is "" on success, otherwise a
    short human-readable reason for the caller to record (e.g. as
    MessageDispatch.delivery_note). Never raises — a failed send must
    flow back to the caller as delivery_status='failed', not crash the
    request that triggered dispatch.
    """
    if not TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN not configured"

    try:
        resp = requests.post(
            API_BASE.format(token=TELEGRAM_BOT_TOKEN) + "/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f"Telegram API request failed: {e}"

    try:
        body = resp.json()
    except ValueError:
        return False, f"Telegram API returned non-JSON response (HTTP {resp.status_code})"

    if resp.ok and body.get("ok"):
        return True, ""
    return False, body.get("description", f"Telegram API error (HTTP {resp.status_code})")

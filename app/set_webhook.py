"""
One-shot Telegram webhook registration — run once per deployment URL:

    python -m app.set_webhook

Reads TELEGRAM_BOT_TOKEN + TELEGRAM_WEBHOOK_SECRET from the environment and
the public base URL from RENDER_EXTERNAL_URL (auto-injected by Render) or
--url. Calls setWebhook so Telegram POSTs updates to
<base>/api/telegram/webhook carrying our secret_token, then prints
getWebhookInfo to confirm.

Deliberately a manual script, NOT a FastAPI startup hook: registration only
needs to happen once per (stable) Render URL, and putting an outbound
Telegram call in the boot path would add a failure/latency mode to every
cold start — exactly what the webhook migration is trying to keep fast.
Same run-once idiom as app/seed.py / app/seed_boq_maize.py.

    python -m app.set_webhook --delete   # deregister (revert to polling for
                                         # local dev with a DEV bot token)

NOTE: a webhook and getUpdates() are mutually exclusive per bot token —
Telegram 409s any poller while a webhook is set. Never point a webhook at
the SAME token a local poller uses; use a separate dev bot token. See
STARTUP.md.
"""
import argparse
import os
import sys

import requests

WEBHOOK_PATH = "/api/telegram/webhook"


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def set_webhook(token: str, base_url: str, secret: str) -> None:
    url = base_url.rstrip("/") + WEBHOOK_PATH
    resp = requests.post(
        _api(token, "setWebhook"),
        json={
            "url": url,
            "secret_token": secret,
            # handle_update only ever acts on message updates; restricting
            # here keeps edited_message / callback_query noise off the
            # endpoint entirely.
            "allowed_updates": ["message"],
        },
        timeout=15,
    )
    resp.raise_for_status()
    print(f"setWebhook -> {url}")
    print(resp.json())


def delete_webhook(token: str) -> None:
    resp = requests.post(_api(token, "deleteWebhook"), timeout=15)
    resp.raise_for_status()
    print("deleteWebhook")
    print(resp.json())


def show_info(token: str) -> None:
    resp = requests.get(_api(token, "getWebhookInfo"), timeout=15)
    resp.raise_for_status()
    print("getWebhookInfo:")
    print(resp.json())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register or deregister the CORWADO Telegram webhook."
    )
    parser.add_argument("--url", help="Public base URL (default: $RENDER_EXTERNAL_URL).")
    parser.add_argument(
        "--delete", action="store_true",
        help="Deregister the webhook (revert to getUpdates polling).",
    )
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is not set.")

    if args.delete:
        delete_webhook(token)
        show_info(token)
        return

    base_url = args.url or os.getenv("RENDER_EXTERNAL_URL")
    if not base_url:
        sys.exit(
            "No public URL: set $RENDER_EXTERNAL_URL or pass "
            "--url https://your-service.onrender.com"
        )

    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not secret:
        sys.exit("TELEGRAM_WEBHOOK_SECRET is not set (the webhook endpoint requires it).")

    set_webhook(token, base_url, secret)
    show_info(token)


if __name__ == "__main__":
    main()

"""Register StockBot's Telegram webhook without echoing credentials."""

import asyncio
from getpass import getpass
import re
from urllib.parse import urlsplit

from telegram import Bot
from telegram.error import TelegramError


def _valid_endpoint(value):
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.path == "/api/telegram"
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
    )


async def _register(endpoint, token, secret):
    async with Bot(token) as bot:
        await bot.set_webhook(
            url=endpoint,
            secret_token=secret,
            max_connections=1,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=False,
        )
        info = await bot.get_webhook_info()
        return info.url == endpoint, info.pending_update_count, info.last_error_date


def main():
    endpoint = input("Vercel HTTPS endpoint (https://<domain>/api/telegram): ").strip()
    if not _valid_endpoint(endpoint):
        print("Use the exact HTTPS endpoint ending in /api/telegram.")
        return 2
    token = getpass("New Telegram bot token (hidden): ").strip()
    secret = getpass("Vercel TELEGRAM_WEBHOOK_SECRET (hidden): ").strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret or ""):
        print("The token or webhook secret is missing or invalid; no webhook was registered.")
        return 2
    try:
        matches, pending, last_error = asyncio.run(_register(endpoint, token, secret))
    except TelegramError:
        print("Telegram rejected the webhook request. Check the new token and endpoint privately.")
        return 1
    except Exception:
        print("Webhook registration failed. No credential details were displayed.")
        return 1
    if not matches:
        print("Telegram did not report the requested endpoint. Check the webhook configuration.")
        return 1
    print("Webhook registered for the requested endpoint.")
    print(f"Pending updates: {pending}")
    if last_error:
        print("Telegram reports a recent delivery error; inspect the endpoint configuration.")
        return 1
    print("No recent Telegram delivery error is reported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""HTTPS webhook entry point for Vercel Python Functions."""

import asyncio
import base64
import hmac
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

from bot_helpers import load_env_file, parse_allowed_ids, resolve_config_value
from postgres_storage import PostgresInventoryManager
from telegram import Update
from telegram.error import TelegramError

from telegram_bot import BASE, EXPECTED_BOT_USERNAME, build_application
from webhook_runtime import PostgresBotPersistence


LOG = logging.getLogger("stockbot.webhook")
MAX_BODY_BYTES = 1_000_000
WEBHOOK_PATH = "/api/telegram"


def _safe_certificate_path(config):
    encoded, _ = resolve_config_value("DATABASE_SSL_ROOT_CERT_B64", config)
    if not encoded:
        raise RuntimeError("DATABASE_SSL_ROOT_CERT_B64 is not configured")
    try:
        certificate = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise RuntimeError("Supabase root certificate configuration is invalid") from exc
    if b"-----BEGIN CERTIFICATE-----" not in certificate:
        raise RuntimeError("Supabase root certificate configuration is invalid")
    descriptor, target = tempfile.mkstemp(
        prefix="stockbot-supabase-", suffix=".crt", dir=tempfile.gettempdir()
    )
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(certificate)
    return Path(target)


def _webhook_secret(config=None):
    config = config if config is not None else load_env_file(BASE / ".env")
    secret, _ = resolve_config_value("TELEGRAM_WEBHOOK_SECRET", config)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret or ""):
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is not configured correctly")
    return secret


def _runtime_config():
    config = load_env_file(BASE / ".env")
    token, _ = resolve_config_value("TELEGRAM_BOT_TOKEN", config)
    secret = _webhook_secret(config)
    database_url, _ = resolve_config_value("DATABASE_URL", config)
    access_mode, _ = resolve_config_value("BOT_ACCESS_MODE", config, default="public")
    backend, _ = resolve_config_value("STORAGE_BACKEND", config, default="postgres")
    low_raw, _ = resolve_config_value("LOW_STOCK_LIMIT", config, default="5")
    allowed_raw, _ = resolve_config_value(
        "TELEGRAM_ALLOWED_USER_IDS", config, aliases=("TELEGRAM_ALLOWED_IDS",)
    )
    admin_raw, _ = resolve_config_value("TELEGRAM_ADMIN_USER_IDS", config)
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    if access_mode != "public" or backend != "postgres":
        raise RuntimeError("The webhook requires public access with PostgreSQL storage")
    try:
        low_limit = int(low_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("LOW_STOCK_LIMIT must be a non-negative integer") from exc
    if low_limit < 0:
        raise RuntimeError("LOW_STOCK_LIMIT must be a non-negative integer")
    allowed_ids = parse_allowed_ids(allowed_raw)
    admin_ids = parse_allowed_ids(admin_raw)
    cert_path = _safe_certificate_path(config)
    return token, secret, database_url, low_limit, allowed_ids, admin_ids, cert_path


def _private_telegram_user(payload):
    message = payload.get("message")
    if isinstance(message, dict):
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
    else:
        callback = payload.get("callback_query")
        if not isinstance(callback, dict):
            return None
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        sender = callback.get("from") or {}
    if chat.get("type") != "private":
        return None
    user_id = sender.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        return None
    return user_id


async def _process_update(payload, user_id):
    token, _, database_url, low_limit, allowed_ids, admin_ids, cert_path = _runtime_config()
    try:
        stock = PostgresInventoryManager(
            database_url, low_stock_limit=low_limit, ssl_root_cert=cert_path,
        )
        scoped = stock.for_user(user_id)
        scoped.ensure_account()
        claim = scoped.claim_webhook_update(payload["update_id"])
        if claim in {"duplicate", "busy"}:
            return claim

        application = build_application(
            token, allowed_ids, stock, access_mode="public", admin_ids=admin_ids,
            persistence=PostgresBotPersistence(stock, user_id),
        )
        succeeded = False
        initialized = False
        try:
            await application.initialize()
            initialized = True
            username = (application.bot.username or "").casefold()
            if username != EXPECTED_BOT_USERNAME.casefold():
                raise RuntimeError("Configured Telegram bot identity did not match")
            update = Update.de_json(payload, application.bot)
            await application.process_update(update)
            if application.bot_data.get("_webhook_handler_error"):
                raise RuntimeError("Telegram update handler reported an error")
            await application.update_persistence()
            succeeded = True
        except Exception as exc:
            LOG.error("Webhook processing failed (%s)", type(exc).__name__)
            raise
        finally:
            try:
                if initialized:
                    await application.shutdown()
            finally:
                scoped.finish_webhook_update(payload["update_id"], succeeded=succeeded)
        return "processed"
    finally:
        try:
            cert_path.unlink(missing_ok=True)
        except OSError:
            LOG.warning("Could not remove temporary database certificate")


def process_webhook(payload, supplied_secret):
    """Validate and process one webhook payload; return an HTTP status code."""
    try:
        expected_secret = _webhook_secret()
    except Exception as exc:
        LOG.error("Webhook configuration failed (%s)", type(exc).__name__)
        return 503
    if not supplied_secret or not hmac.compare_digest(supplied_secret, expected_secret):
        return 401
    if not isinstance(payload, dict):
        return 400
    update_id = payload.get("update_id")
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        return 400
    user_id = _private_telegram_user(payload)
    if user_id is None:
        # Unsupported update types and non-private chats do not touch inventory.
        return 200
    try:
        outcome = asyncio.run(_process_update(payload, user_id))
    except (TelegramError, OSError, RuntimeError, ValueError) as exc:
        LOG.error("Webhook processing failed (%s)", type(exc).__name__)
        return 503
    except Exception as exc:
        LOG.error("Unexpected webhook failure (%s)", type(exc).__name__)
        return 503
    return 503 if outcome == "busy" else 200


class handler(BaseHTTPRequestHandler):
    """Vercel's Python HTTP handler contract."""

    def _respond(self, status, body):
        response = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self):
        if urlsplit(self.path).path != WEBHOOK_PATH:
            return self._respond(404, {"ok": False})
        return self._respond(200, {"ok": True})

    def do_POST(self):
        if urlsplit(self.path).path != WEBHOOK_PATH:
            return self._respond(404, {"ok": False})
        supplied_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        # Reject invalid secrets before reading the request body.
        try:
            expected_secret = _webhook_secret()
        except Exception as exc:
            LOG.error("Webhook configuration failed (%s)", type(exc).__name__)
            return self._respond(503, {"ok": False})
        if not supplied_secret or not hmac.compare_digest(supplied_secret, expected_secret):
            return self._respond(401, {"ok": False})
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit():
            return self._respond(411, {"ok": False})
        body_length = int(raw_length)
        if body_length < 1 or body_length > MAX_BODY_BYTES:
            return self._respond(413, {"ok": False})
        try:
            payload = json.loads(self.rfile.read(body_length))
        except (ValueError, UnicodeDecodeError):
            return self._respond(400, {"ok": False})
        result = process_webhook(payload, supplied_secret)
        return self._respond(result, {"ok": result == 200})

    def log_message(self, format, *args):
        # BaseHTTPRequestHandler would include paths and may include user data.
        LOG.info("Webhook HTTP request completed")

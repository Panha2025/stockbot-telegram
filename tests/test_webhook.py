"""Webhook endpoint and PostgreSQL-backed PTB persistence tests."""

from contextlib import contextmanager
from decimal import Decimal
from io import BytesIO
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from api import telegram as webhook
from webhook_runtime import PostgresBotPersistence


class MemoryCursor:
    def __init__(self, store):
        self.store = store
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=()):
        compact = " ".join(query.split())
        if compact.startswith("SELECT bot_user_data"):
            self.row = (self.store.state["bot_user_data"],)
        elif compact.startswith("SELECT bot_conversations"):
            self.row = (self.store.state["bot_conversations"],)
        elif compact.startswith("UPDATE public.shop_users SET bot_user_data"):
            self.store.state["bot_user_data"] = json.loads(params[0])
            self.row = None
        elif compact.startswith("UPDATE public.shop_users SET bot_conversations"):
            self.store.state["bot_conversations"] = json.loads(params[0])
            self.row = None
        else:
            raise AssertionError(f"Unexpected persistence query: {compact}")

    def fetchone(self):
        return self.row


class MemoryStore:
    def __init__(self):
        self.state = {"bot_user_data": {}, "bot_conversations": {}}

    @contextmanager
    def _connection(self, _user_id):
        class Connection:
            def __init__(self, store):
                self.store = store

            def cursor(self):
                return MemoryCursor(self.store)

        yield Connection(self)


class WebhookHTTPTests(unittest.TestCase):
    def post(self, payload, secret="unit-secret"):
        request = object.__new__(webhook.handler)
        request.path = "/api/telegram"
        request.headers = {
            "Content-Length": str(len(json.dumps(payload).encode())),
            "X-Telegram-Bot-Api-Secret-Token": secret,
        }
        request.rfile = BytesIO(json.dumps(payload).encode())
        request.wfile = BytesIO()
        request.send_response = MagicMock()
        request.send_header = MagicMock()
        request.end_headers = MagicMock()
        request.do_POST()
        status = request.send_response.call_args.args[0]
        body = json.loads(request.wfile.getvalue())
        return status, body

    def test_invalid_webhook_secret_is_rejected_before_processing(self):
        payload = {"update_id": 1}
        with patch.object(webhook, "_webhook_secret", return_value="unit-secret"), \
             patch.object(webhook, "_process_update", new=AsyncMock()) as process:
            status, body = self.post(payload, secret="wrong-secret")
        self.assertEqual((status, body), (401, {"ok": False}))
        process.assert_not_awaited()

    def test_duplicate_webhook_delivery_is_acknowledged(self):
        payload = {
            "update_id": 2,
            "message": {
                "from": {"id": 101},
                "chat": {"id": 101, "type": "private"},
                "text": "/start",
            },
        }
        with patch.object(webhook, "_webhook_secret", return_value="unit-secret"), \
             patch.object(webhook, "_process_update", new=AsyncMock(return_value="duplicate")) as process:
            status, body = self.post(payload)
        self.assertEqual((status, body), (200, {"ok": True}))
        process.assert_awaited_once_with(payload, 101)

    def test_non_private_update_is_acknowledged_without_inventory_processing(self):
        payload = {
            "update_id": 3,
            "message": {
                "from": {"id": 102},
                "chat": {"id": -100, "type": "group"},
                "text": "/start",
            },
        }
        with patch.object(webhook, "_webhook_secret", return_value="unit-secret"), \
             patch.object(webhook, "_process_update", new=AsyncMock()) as process:
            status, body = self.post(payload)
        self.assertEqual((status, body), (200, {"ok": True}))
        process.assert_not_awaited()


class PostgresPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_state_and_conversation_survive_new_persistence_instance(self):
        store = MemoryStore()
        first = PostgresBotPersistence(store, 123)
        await first.update_user_data(123, {"draft_price": Decimal("1.25")})
        await first.update_conversation("stockbot_user_conversation", (123, 123), 4)

        restarted = PostgresBotPersistence(store, 123)
        user_data = await restarted.get_user_data()
        conversations = await restarted.get_conversations("stockbot_user_conversation")

        self.assertEqual(user_data, {123: {"draft_price": Decimal("1.25")}})
        self.assertEqual(conversations, {(123, 123): 4})

    async def test_persistence_is_bound_to_its_telegram_user(self):
        store = MemoryStore()
        persistence = PostgresBotPersistence(store, 123)
        await persistence.update_user_data(456, {"other": True})
        await persistence.update_conversation("flow", (456, 456), 3)
        self.assertEqual(store.state, {"bot_user_data": {}, "bot_conversations": {}})


if __name__ == "__main__":
    unittest.main()

"""Mocked Telegram-handler tests; no token or network is needed."""
import importlib
import contextlib
from io import StringIO
import sys
import types
import unittest
import warnings
from unittest.mock import AsyncMock, patch

from inventory import InventoryManager
from storage import InventoryStorage


def _fake_telegram_modules():
    class KeyboardButton:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    class KeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    telegram = types.ModuleType("telegram")
    telegram.BotCommand = type("BotCommand", (), {})
    telegram.InlineKeyboardButton = KeyboardButton
    telegram.InlineKeyboardMarkup = KeyboardMarkup
    telegram.Update = type("Update", (), {})
    ext = types.ModuleType("telegram.ext")
    ext.ApplicationHandlerStop = type("ApplicationHandlerStop", (Exception,), {})
    ext.Application = type("Application", (), {})
    ext.CallbackQueryHandler = type("CallbackQueryHandler", (), {})
    ext.CommandHandler = type("CommandHandler", (), {})
    ext.ContextTypes = types.SimpleNamespace()
    ext.ConversationHandler = type("ConversationHandler", (), {"END": -1})
    ext.MessageHandler = type("MessageHandler", (), {})
    ext.TypeHandler = type("TypeHandler", (), {})
    ext.filters = types.SimpleNamespace(TEXT=object(), COMMAND=object())
    # Used only if the optional dependency is missing in the test environment.
    telegram_warnings = types.ModuleType("telegram.warnings")
    telegram_warnings.PTBUserWarning = Warning
    telegram_error = types.ModuleType("telegram.error")
    for name in ("Conflict", "InvalidToken", "NetworkError", "TelegramError"):
        setattr(telegram_error, name, type(name, (Exception,), {}))
    return {
        "telegram": telegram, "telegram.ext": ext,
        "telegram.warnings": telegram_warnings, "telegram.error": telegram_error,
    }


try:
    import telegram_bot
    _HAS_REAL_TELEGRAM = True
except SystemExit:
    # Importing the optional integration normally explains the missing library;
    # tests substitute lightweight API names and exercise the real handlers.
    with patch.dict(sys.modules, _fake_telegram_modules()):
        telegram_bot = importlib.import_module("telegram_bot")
    _HAS_REAL_TELEGRAM = False


class TelegramHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = InventoryManager(InventoryStorage(f"{self.temp.name}/inventory.json"))
        self.reply_text = AsyncMock()
        self.user = types.SimpleNamespace(id=123)
        self.chat = types.SimpleNamespace(type="private")
        self.message = types.SimpleNamespace(text="P017", reply_text=self.reply_text)
        self.update = types.SimpleNamespace(
            message=self.message, callback_query=None, effective_message=self.message,
            effective_user=self.user, effective_chat=self.chat,
        )
        self.context = types.SimpleNamespace(
            application=types.SimpleNamespace(bot_data={"manager": self.manager, "allowed_ids": {123}}),
            user_data={}, user_id=123,
        )

    def set_callback(self, data):
        message = types.SimpleNamespace(reply_text=AsyncMock())
        query = types.SimpleNamespace(data=data, answer=AsyncMock(), message=message)
        self.update.callback_query = query
        return query

    async def test_authorization_blocks_unlisted_user_before_inventory_response(self):
        self.user.id = 456
        self.assertFalse(await telegram_bot.authorized(self.update, self.context))
        self.reply_text.assert_awaited_once()
        self.assertIn("Access denied", self.reply_text.await_args.args[0])

    async def test_public_mode_onboards_verified_private_user_without_allowlist(self):
        class Scoped:
            def __init__(self):
                self.created = 0
            def ensure_account(self):
                self.created += 1
            def summary(self):
                return {"total_products": 0, "total_units": 0, "inventory_value": "0.00", "low_stock_count": 0}

        class Store:
            def __init__(self):
                self.accounts = {}
            def for_user(self, user_id):
                return self.accounts.setdefault(user_id, Scoped())

        store = Store()
        self.context.application.bot_data.update(manager=store, access_mode="public", allowed_ids=set())
        await telegram_bot.home(self.update, self.context)
        self.assertEqual(set(store.accounts), {123})
        self.assertEqual(store.accounts[123].created, 1)
        self.assertIn("private inventory", self.reply_text.await_args.args[0])

    async def test_public_mode_still_rejects_group_updates(self):
        self.context.application.bot_data.update(access_mode="public", allowed_ids=set())
        self.chat.type = "group"
        self.assertFalse(await telegram_bot.authorized(self.update, self.context))
        self.assertIn("private chat", self.reply_text.await_args.args[0])

    async def test_scoped_manager_uses_context_verified_telegram_user(self):
        class Store:
            def for_user(self, user_id):
                return ("scoped", user_id)
        self.context.application.bot_data["manager"] = Store()
        self.assertEqual(telegram_bot.manager(self.context), ("scoped", 123))

    async def test_public_application_refuses_shared_local_json_storage(self):
        with self.assertRaisesRegex(ValueError, "user-scoped PostgreSQL"):
            telegram_bot.build_application("placeholder", set(), self.manager, access_mode="public")

    async def test_public_configuration_rejects_json_backend(self):
        output = StringIO()
        with patch.dict("os.environ", {
            "TELEGRAM_BOT_TOKEN": "dummy-test-value",
            "BOT_ACCESS_MODE": "public",
            "STORAGE_BACKEND": "json",
        }, clear=True), patch.object(telegram_bot, "load_env_file", return_value={}), \
             contextlib.redirect_stdout(output):
            result = telegram_bot.main()
        self.assertEqual(result, 1)
        self.assertIn("Public access requires PostgreSQL", output.getvalue())
        self.assertNotIn("dummy-test-value", output.getvalue())

    async def test_global_rate_limit_covers_each_user_update(self):
        update = types.SimpleNamespace(update_id=None)
        with patch.object(telegram_bot.time, "monotonic", return_value=100.0):
            allowed = [telegram_bot._within_rate_limit(update, self.context, 123) for _ in range(61)]
        self.assertEqual(sum(allowed), telegram_bot.RATE_LIMIT_PER_MINUTE)

    async def test_public_delete_account_requires_matching_confirmation(self):
        class Scoped:
            def __init__(self):
                self.deleted = 0
                self.created = 0
            def ensure_account(self):
                self.created += 1
            def delete_account(self):
                self.deleted += 1
                return True
        class Store:
            def __init__(self):
                self.accounts = {}
            def for_user(self, user_id):
                return self.accounts.setdefault(user_id, Scoped())
        store = Store()
        self.context.application.bot_data.update(manager=store, access_mode="public")
        self.context.user_data[telegram_bot.ACCOUNT_DELETE_KEY] = "one_nonce"
        query = self.set_callback("account:delete:other_nonce")
        await telegram_bot.delete_account_callback(self.update, self.context)
        self.assertEqual(store.accounts, {})
        query = self.set_callback("account:delete:one_nonce")
        await telegram_bot.delete_account_callback(self.update, self.context)
        self.assertEqual(store.accounts[123].deleted, 1)
        self.assertEqual(store.accounts[123].created, 0)
        self.assertIn("permanently deleted", query.message.reply_text.await_args.args[0])

    async def prepare_add_preview(self, category="Stationery"):
        await telegram_bot.add_start(self.update, self.context)
        nonce = self.context.user_data["add_draft"]["nonce"]
        self.message.text = "Pencil"
        self.assertEqual(await telegram_bot.add_name(self.update, self.context), telegram_bot.ADD_CATEGORY)
        query = self.set_callback(f"addcat:{category}:{nonce}")
        self.assertEqual(await telegram_bot.add_category_choice(self.update, self.context), telegram_bot.ADD_QUANTITY)
        query.answer.assert_awaited_once()
        self.update.callback_query = None
        self.message.text = "20"
        self.assertEqual(await telegram_bot.add_quantity(self.update, self.context), telegram_bot.ADD_PRICE)
        self.message.text = "0.50"
        self.assertEqual(await telegram_bot.add_price(self.update, self.context), telegram_bot.ADD_CONFIRM)
        self.assertEqual(self.manager.list_products(), [])
        return nonce

    async def test_add_requires_confirmation_and_generates_id_once(self):
        nonce = await self.prepare_add_preview()
        self.assertIn("Total Stock Value: $10.00", self.reply_text.await_args.args[0])
        self.set_callback(f"add:save:{nonce}")
        state = await telegram_bot.add_confirmation(self.update, self.context)
        self.assertEqual(state, telegram_bot.ConversationHandler.END)
        self.assertEqual(self.manager.get("P001").name, "Pencil")
        restored = InventoryManager(InventoryStorage(self.manager.storage.path))
        self.assertEqual(restored.get("P001").name, "Pencil")
        self.set_callback(f"add:save:{nonce}")
        await telegram_bot.add_confirmation(self.update, self.context)
        self.assertEqual(len(self.manager.list_products()), 1)

    async def test_add_cancellation_does_not_change_inventory(self):
        nonce = await self.prepare_add_preview()
        self.set_callback(f"add:cancel:{nonce}")
        await telegram_bot.add_confirmation(self.update, self.context)
        self.assertEqual(self.manager.list_products(), [])
        self.assertNotIn("add_draft", self.context.user_data)

    async def test_add_preview_edit_details_returns_to_confirmation(self):
        nonce = await self.prepare_add_preview()
        self.set_callback(f"add:edit:{nonce}")
        self.assertEqual(await telegram_bot.add_edit_field(self.update, self.context), telegram_bot.ADD_EDIT_FIELD)
        self.set_callback(f"addfield:quantity:{nonce}")
        self.assertEqual(await telegram_bot.add_edit_value_start(self.update, self.context), telegram_bot.ADD_EDIT_VALUE)
        self.update.callback_query = None
        self.message.text = "25"
        self.assertEqual(await telegram_bot.add_edit_value(self.update, self.context), telegram_bot.ADD_CONFIRM)
        self.assertIn("Quantity: 25", self.reply_text.await_args.args[0])
        self.set_callback(f"add:save:{nonce}")
        await telegram_bot.add_confirmation(self.update, self.context)
        self.assertEqual(self.manager.get("P001").quantity, 25)

    async def test_custom_category_and_invalid_quantity_or_price(self):
        await telegram_bot.add_start(self.update, self.context)
        nonce = self.context.user_data["add_draft"]["nonce"]
        self.message.text = "Pencil"
        await telegram_bot.add_name(self.update, self.context)
        self.set_callback(f"addcat:custom:{nonce}")
        self.assertEqual(await telegram_bot.add_category_choice(self.update, self.context), telegram_bot.ADD_CUSTOM_CATEGORY)
        self.update.callback_query = None
        self.message.text = "Art Supplies"
        await telegram_bot.add_custom_category(self.update, self.context)
        self.message.text = "not-a-number"
        self.assertEqual(await telegram_bot.add_quantity(self.update, self.context), telegram_bot.ADD_QUANTITY)
        self.message.text = "4"
        await telegram_bot.add_quantity(self.update, self.context)
        self.message.text = "-1.00"
        self.assertEqual(await telegram_bot.add_price(self.update, self.context), telegram_bot.ADD_PRICE)
        self.assertEqual(self.manager.list_products(), [])

    async def test_category_buttons_include_requested_categories_and_custom(self):
        keyboard = telegram_bot.category_keyboard("addcat", "abc123")
        labels = [entry.text for row in keyboard.inline_keyboard for entry in row]
        self.assertEqual(labels[:7], list(telegram_bot.CATEGORIES))
        self.assertIn("✍️ Enter a custom category", labels)

    async def test_cancel_delete_callback_does_not_change_inventory(self):
        item = self.manager.add("Tea", "Drinks", 1, "1.00")
        self.assertEqual(await telegram_bot.prepare_delete(self.update, self.context, item.id), telegram_bot.DELETE_CONFIRM)
        nonce = self.context.user_data["delete_nonce"]
        self.set_callback(f"delete:no:{item.id}:{nonce}")
        state = await telegram_bot.delete_confirm(self.update, self.context)
        self.assertEqual(state, telegram_bot.ConversationHandler.END)
        self.assertEqual(len(self.manager.list_products()), 1)
        self.assertIn("No data changed", self.update.callback_query.message.reply_text.await_args.args[0])

    async def test_confirm_delete_removes_product_and_stale_tap_is_safe(self):
        item = self.manager.add("Tea", "Drinks", 1, "1.00")
        await telegram_bot.prepare_delete(self.update, self.context, item.id)
        nonce = self.context.user_data["delete_nonce"]
        self.set_callback(f"delete:yes:{item.id}:{nonce}")
        await telegram_bot.delete_confirm(self.update, self.context)
        self.assertEqual(self.manager.list_products(), [])
        await telegram_bot.delete_confirm(self.update, self.context)
        self.assertEqual(self.manager.list_products(), [])

    async def test_myid_works_without_allowlist_and_inventory_context(self):
        self.context.application.bot_data["allowed_ids"] = set()
        self.context.application.bot_data.pop("manager")
        await telegram_bot.whoami(self.update, self.context)
        self.assertIn("123", self.reply_text.await_args.args[0])

    async def test_authorized_configured_id_can_open_start_menu(self):
        with patch.object(telegram_bot, "main_keyboard", return_value="menu-keyboard"):
            await telegram_bot.home(self.update, self.context)
        self.assertIn("SMALL SHOP INVENTORY", self.reply_text.await_args.args[0])
        self.assertEqual(self.reply_text.await_args.kwargs["reply_markup"], "menu-keyboard")

    async def test_view_pagination_uses_five_products(self):
        for number in range(11):
            self.manager.add(f"Item {number}", "Other", number, "1.00")
        await telegram_bot.show_products(self.update, self.context)
        output = self.reply_text.await_args.args[0]
        self.assertIn("Page 1 of 3", output)
        self.assertIn("P005", output)
        self.assertNotIn("P006", output)

    async def test_search_is_partial_case_insensitive_and_has_no_result_message(self):
        self.manager.add("Pencil", "Stationery", 4, "0.50")
        await telegram_bot.search_display(self.update, self.context, "pEN")
        self.assertIn("Pencil", self.reply_text.await_args.args[0])
        self.reply_text.reset_mock()
        await telegram_bot.search_display(self.update, self.context, "not present")
        self.assertIn("No products found. Try another keyword.", self.reply_text.await_args.args[0])

    async def test_low_stock_action_updates_quantity_after_preview_confirmation(self):
        product = self.manager.add("Notebook", "Stationery", 2, "1.00")
        self.set_callback(f"item:stock:{product.id}:low:0")
        self.assertEqual(await telegram_bot.start_low_stock_edit(self.update, self.context), telegram_bot.EDIT_VALUE)
        nonce = self.context.user_data["edit_nonce"]
        self.update.callback_query = None
        self.message.text = "9"
        self.assertEqual(await telegram_bot.edit_value(self.update, self.context), telegram_bot.EDIT_CONFIRM)
        self.assertEqual(self.manager.get(product.id).quantity, 2)
        self.set_callback(f"editconfirm:save:{nonce}")
        await telegram_bot.edit_confirm(self.update, self.context)
        self.assertEqual(self.manager.get(product.id).quantity, 9)

    async def test_edit_field_requires_preview_then_confirms(self):
        product = self.manager.add("Pencil", "Stationery", 20, "0.50")
        await telegram_bot.select_edit_product(self.update, self.context, product.id)
        nonce = self.context.user_data["edit_nonce"]
        self.set_callback(f"editfield:quantity:{nonce}")
        self.assertEqual(await telegram_bot.edit_field(self.update, self.context), telegram_bot.EDIT_VALUE)
        self.update.callback_query = None
        self.message.text = "7"
        self.assertEqual(await telegram_bot.edit_value(self.update, self.context), telegram_bot.EDIT_CONFIRM)
        self.assertEqual(self.manager.get(product.id).quantity, 20)
        self.set_callback(f"editconfirm:save:{nonce}")
        await telegram_bot.edit_confirm(self.update, self.context)
        self.assertEqual(self.manager.get(product.id).quantity, 7)

    async def test_low_stock_picker_offers_stock_update(self):
        self.manager.add("Notebook", "Stationery", 2, "1.00")
        await telegram_bot.show_low(self.update, self.context)
        keyboard = self.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
        callback_data = [button.callback_data for row in keyboard for button in row]
        self.assertIn("item:stock:P001:low:0", callback_data)

    async def test_startup_preflight_is_read_only_and_checks_bot_and_webhook(self):
        bot = types.SimpleNamespace(
            get_me=AsyncMock(return_value=types.SimpleNamespace(username="SmallShopInventory221Bot")),
            get_webhook_info=AsyncMock(return_value=types.SimpleNamespace(url="")),
        )
        await telegram_bot.preflight_telegram(types.SimpleNamespace(bot=bot))
        bot.get_me.assert_awaited_once()
        bot.get_webhook_info.assert_awaited_once()
        self.assertFalse(hasattr(bot, "delete_webhook"))

        bot.get_webhook_info.return_value = types.SimpleNamespace(url="https://example.invalid/hook")
        with self.assertRaises(telegram_bot.ExistingWebhookError):
            await telegram_bot.preflight_telegram(types.SimpleNamespace(bot=bot))

    async def test_preflight_rejects_a_token_for_another_bot(self):
        bot = types.SimpleNamespace(
            get_me=AsyncMock(return_value=types.SimpleNamespace(username="DifferentBot")),
            get_webhook_info=AsyncMock(),
        )
        with self.assertRaises(telegram_bot.BotIdentityError):
            await telegram_bot.preflight_telegram(types.SimpleNamespace(bot=bot))
        bot.get_webhook_info.assert_not_awaited()

    @unittest.skipUnless(_HAS_REAL_TELEGRAM, "PTB application construction needs python-telegram-bot")
    async def test_application_registers_myid_before_conversation_and_warning_is_suppressed(self):
        with warnings.catch_warnings(record=True) as caught:
            with patch.object(telegram_bot, "BASE", self.manager.storage.path.parent):
                application = telegram_bot.build_application(
                    "000000:placeholder", set(), self.manager,
                )
        first = application.handlers[0][0]
        self.assertEqual(first.commands, frozenset({"myid"}))
        self.assertFalse(any("per_message=False" in str(item.message) for item in caught))

    async def test_command_logging_omits_arguments(self):
        self.update.message.text = "/search private customer detail"
        with self.assertLogs(telegram_bot.LOG, level="INFO") as captured:
            await telegram_bot.log_incoming_command(self.update, self.context)
        output = "\n".join(captured.output)
        self.assertIn("Received /search", output)
        self.assertNotIn("private customer detail", output)

    async def test_startup_reports_missing_token_without_disclosing_any_value(self):
        output = StringIO()
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(telegram_bot, "load_env_file", return_value={}), \
             contextlib.redirect_stdout(output):
            result = telegram_bot.main()
        self.assertEqual(result, 1)
        self.assertIn("Missing TELEGRAM_BOT_TOKEN", output.getvalue())

    @unittest.skipUnless(_HAS_REAL_TELEGRAM, "PTB API error classes need python-telegram-bot")
    async def test_startup_reports_invalid_token_without_disclosing_it(self):
        output = StringIO()
        fake_application = types.SimpleNamespace(
            run_polling=unittest.mock.Mock(side_effect=telegram_bot.InvalidToken("sensitive value"))
        )
        config = {"TELEGRAM_BOT_TOKEN": "sensitive-value-for-test", "TELEGRAM_ALLOWED_USER_IDS": ""}
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(telegram_bot, "load_env_file", return_value=config), \
             patch.object(telegram_bot, "build_application", return_value=fake_application), \
             contextlib.redirect_stdout(output):
            result = telegram_bot.main()
        self.assertEqual(result, 1)
        self.assertIn("Invalid TELEGRAM_BOT_TOKEN", output.getvalue())
        self.assertNotIn("sensitive-value-for-test", output.getvalue())
        self.assertNotIn("sensitive value", output.getvalue())


if __name__ == "__main__":
    unittest.main()

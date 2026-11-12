"""Telegram-related tests that do not need internet access or a bot token."""
import tempfile
import unittest
from pathlib import Path

from bot_helpers import (
    is_authorized_user, load_env_file, parse_allowed_ids, parse_callback_action,
    resolve_config_value,
    product_page, summary_text,
)
from inventory import InventoryManager
from storage import InventoryStorage


class BotHelpersTests(unittest.TestCase):
    def test_allowlist_missing_locks_bot(self):
        self.assertEqual(parse_allowed_ids(""), set())

    def test_allowlist_multiple_ids(self):
        self.assertEqual(parse_allowed_ids("123, 456,123"), {123, 456})

    def test_allowlist_rejects_invalid(self):
        for raw in ("abc", "1,", "-2", "0", "1;2"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_allowed_ids(raw)

    def test_empty_process_allowlist_falls_back_to_dotenv(self):
        value, source = resolve_config_value(
            "TELEGRAM_ALLOWED_USER_IDS",
            {"TELEGRAM_ALLOWED_USER_IDS": "123456789"},
            environ={"TELEGRAM_ALLOWED_USER_IDS": ""},
        )
        self.assertEqual(value, "123456789")
        self.assertEqual(source, ".env:TELEGRAM_ALLOWED_USER_IDS")

    def test_nonempty_process_allowlist_overrides_dotenv(self):
        value, source = resolve_config_value(
            "TELEGRAM_ALLOWED_USER_IDS",
            {"TELEGRAM_ALLOWED_USER_IDS": "123456789"},
            environ={"TELEGRAM_ALLOWED_USER_IDS": "987654321"},
        )
        self.assertEqual(value, "987654321")
        self.assertEqual(source, "environment:TELEGRAM_ALLOWED_USER_IDS")

    def test_legacy_allowlist_alias_remains_supported(self):
        value, source = resolve_config_value(
            "TELEGRAM_ALLOWED_USER_IDS", {"TELEGRAM_ALLOWED_IDS": "123456789"},
            environ={}, aliases=("TELEGRAM_ALLOWED_IDS",),
        )
        self.assertEqual(value, "123456789")
        self.assertEqual(source, ".env:TELEGRAM_ALLOWED_IDS")

    def test_env_file_is_only_key_values(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / ".env"
            file.write_text("# demo\nTELEGRAM_ALLOWED_IDS='123'\nFOO=bar\nnot a key\n", encoding="utf-8")
            self.assertEqual(load_env_file(file)["TELEGRAM_ALLOWED_IDS"], "123")
            self.assertNotIn("not a key", load_env_file(file))

    def test_inventory_page(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory = InventoryManager(InventoryStorage(Path(temp) / "demo.json"))
            for index in range(7):
                inventory.add(f"Item {index}", "Demo", index, "1.00")
            text, page, pages = product_page(inventory.list_products(), 1)
            self.assertEqual((page, pages), (1, 2))
            self.assertIn("Item 6", text)
            self.assertNotIn("Item 0", text)

    def test_summary_text(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory = InventoryManager(InventoryStorage(Path(temp) / "demo.json"))
            inventory.add("Paper", "Stationery", 2, "2.50")
            message = summary_text(inventory.summary())
            self.assertIn("Total units: 2", message)
            self.assertIn("$5.00", message)

    def test_telegram_authorization_requires_allowlisted_user_in_private_chat(self):
        allowed = {123, 456}
        self.assertTrue(is_authorized_user(123, "private", allowed))
        self.assertFalse(is_authorized_user(999, "private", allowed))
        self.assertFalse(is_authorized_user(123, "group", allowed))
        self.assertFalse(is_authorized_user(None, "private", allowed))
        self.assertFalse(is_authorized_user(123, "private", set()))

    def test_callback_actions_are_validated(self):
        self.assertEqual(parse_callback_action("menu:summary"), "menu:summary")
        self.assertEqual(parse_callback_action("browse:list:2"), "browse:list:2")
        self.assertEqual(parse_callback_action("item:view:P001:list:0"), "item:view:P001:list:0")
        self.assertIsNone(parse_callback_action("delete:yes"))
        self.assertIsNone(parse_callback_action("menu:unknown"))
        self.assertIsNone(parse_callback_action("browse:list:-1"))


if __name__ == "__main__":
    unittest.main()

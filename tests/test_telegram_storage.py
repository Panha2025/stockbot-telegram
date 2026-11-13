"""Tests for isolated local JSON files used by public Telegram polling."""

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from inventory import InventoryError
from telegram_storage import LocalTelegramInventoryManager, MAX_PRODUCTS_PER_USER


class LocalTelegramStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "telegram_users"
        self.store = LocalTelegramInventoryManager(self.directory)

    def test_user_ids_get_private_separate_files_and_ids(self):
        first = self.store.for_user(123456)
        second = self.store.for_user(654321)
        item = first.add("Pen", "Stationery", 4, "0.50")

        self.assertEqual(item.id, "P001")
        self.assertEqual([product.name for product in second.list_products()], [])
        self.assertEqual(second.add("Cup", "Household", 2, "1.25").id, "P001")
        restarted = LocalTelegramInventoryManager(self.directory).for_user(123456)
        self.assertEqual([(p.id, p.name) for p in restarted.list_products()], [("P001", "Pen")])
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)

    def test_ensure_account_and_delete_account_only_touch_that_users_file(self):
        first = self.store.for_user(1001)
        second = self.store.for_user(1002)
        first.ensure_account()
        second.ensure_account()
        first_path, second_path = first.path, second.path
        self.assertTrue(first_path.exists())
        self.assertTrue(second_path.exists())

        self.assertTrue(first.delete_account())
        self.assertFalse(first_path.exists())
        self.assertTrue(second_path.exists())
        self.assertFalse(first.delete_account())

    def test_invalid_user_id_is_rejected_before_creating_a_file(self):
        for user_id in (0, -5, True, "123"):
            with self.subTest(user_id=type(user_id).__name__):
                with self.assertRaises(ValueError):
                    self.store.for_user(user_id)
        self.assertFalse(self.directory.exists())

    def test_account_product_limit_is_preserved(self):
        products = [
            {"id": f"P{number:03d}", "name": f"Item {number}", "category": "Other", "quantity": 1, "price": "1.00"}
            for number in range(1, MAX_PRODUCTS_PER_USER + 1)
        ]
        self.directory.mkdir(mode=0o700)
        path = self.directory / "7001.json"
        initial = {"version": 1, "next_id": MAX_PRODUCTS_PER_USER + 1, "products": products}
        path.write_text(json.dumps(initial), encoding="utf-8")
        before = path.read_bytes()

        with self.assertRaisesRegex(InventoryError, "500 products"):
            self.store.for_user(7001).add("Extra", "Other", 1, "1.00")

        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

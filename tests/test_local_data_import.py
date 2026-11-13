"""Tests for the safe, opt-in import of per-user local Telegram data."""

import json
from pathlib import Path
import tempfile
import unittest

from scripts.import_local_telegram_data import read_local_accounts


class LocalTelegramImportSourceTests(unittest.TestCase):
    def test_reads_separate_account_file_and_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "123456.json"
            original = {
                "version": 1,
                "next_id": 5,
                "products": [
                    {"id": "P002", "name": "Pen", "category": "Stationery", "quantity": 3, "price": "0.50"}
                ],
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()

            accounts = read_local_accounts(directory)

            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].user_id, 123456)
            self.assertEqual(accounts[0].next_product_number, 5)
            self.assertEqual(accounts[0].products[0].id, "P002")
            self.assertEqual(path.read_bytes(), before)

    def test_empty_source_directory_has_nothing_to_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(read_local_accounts(temporary), [])

    def test_rejects_non_numeric_account_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "private.json").write_text(
                json.dumps({"version": 1, "next_id": 1, "products": []}), encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "filename is invalid"):
                read_local_accounts(temporary)


if __name__ == "__main__":
    unittest.main()

"""Additional checks of the terminal interface and safe startup failures."""

import contextlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import display_products, main, run_menu
from inventory import InventoryManager
from storage import InventoryStorage


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_path = Path(self.tmp.name) / "inventory.json"

    def test_menu_add_search_summary_exit(self):
        manager = InventoryManager(InventoryStorage(self.data_path))
        answers = iter([
            "1", "Pencil", "Stationery", "3", "1.25",
            "3", "pencil", "6", "7",
        ])
        output = StringIO()
        with patch("builtins.input", side_effect=lambda prompt="": next(answers)):
            with contextlib.redirect_stdout(output):
                run_menu(manager)
        message = output.getvalue()
        self.assertIn("Added P001", message)
        self.assertIn("Pencil", message)
        self.assertIn("Units in stock:  3", message)
        self.assertIn("$3.75", message)
        self.assertIn("Goodbye", message)

    def test_menu_invalid_input_does_not_stop(self):
        manager = InventoryManager(InventoryStorage(self.data_path))
        answers = iter(["9", "1", "", "Test", "1", "2.00", "7"])
        output = StringIO()
        with patch("builtins.input", side_effect=lambda prompt="": next(answers)):
            with contextlib.redirect_stdout(output):
                run_menu(manager)
        self.assertIn("Please enter a number from 1 to 7", output.getvalue())
        self.assertIn("Item name is required", output.getvalue())
        self.assertEqual(manager.list_products(), [])

    def test_empty_inventory_message(self):
        output = StringIO()
        with contextlib.redirect_stdout(output):
            display_products([])
        self.assertIn("No products found", output.getvalue())

    def test_main_missing_file_opens_then_exits(self):
        with patch("builtins.input", return_value="7"):
            self.assertEqual(main(["--data", str(self.data_path)]), 0)
        self.assertFalse(self.data_path.exists())

    def test_main_damaged_file_preserved(self):
        data = "{ damaged file"
        self.data_path.write_text(data, encoding="utf-8")
        output = StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data", str(self.data_path)]), 1)
        self.assertEqual(self.data_path.read_text(encoding="utf-8"), data)
        self.assertIn("Cannot start", output.getvalue())


if __name__ == "__main__":
    unittest.main()

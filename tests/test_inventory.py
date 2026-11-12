"""Tests for COSC 221's required inventory behaviors. Run: python3 -m unittest discover -s tests -v"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from app import delete_product
from inventory import InventoryError, InventoryManager, ProductNotFound
from storage import DataFileError, InventoryStorage


PROJECT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT / "data" / "inventory.json"


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "inventory.json"
        self.manager = InventoryManager(InventoryStorage(self.path))

    def test_01_missing_file_starts_empty(self):
        self.assertEqual(self.manager.list_products(), [])
        self.assertEqual(self.manager.summary()["total_products"], 0)
        self.assertFalse(self.path.exists())

    def test_02_add_valid_product_and_save(self):
        item = self.manager.add("Apple juice", "Beverages", 8, "2.50")
        self.assertEqual(item.id, "P001")
        self.assertEqual(InventoryManager(InventoryStorage(self.path)).get("P001").name, "Apple juice")

    def test_03_reject_empty_required_fields(self):
        for name, category in (("", "Grocery"), ("Pen", " ")):
            with self.subTest(name=name, category=category):
                with self.assertRaises(InventoryError):
                    self.manager.add(name, category, 3, "1.00")
        self.assertFalse(self.path.exists())

    def test_04_reject_invalid_quantities(self):
        for invalid in (-1, "-1", "3.5", "hello", True, "1000001"):
            with self.subTest(quantity=invalid):
                with self.assertRaises(InventoryError):
                    self.manager.add("Notebook", "Stationery", invalid, "2.00")

    def test_05_reject_invalid_prices(self):
        for invalid in ("-2.00", "2.999", "nope", "NaN", "Infinity", None):
            with self.subTest(price=invalid):
                with self.assertRaises(InventoryError):
                    self.manager.add("Notebook", "Stationery", 3, invalid)

    def test_06_search_found_and_not_found(self):
        self.manager.add("Black Pen", "Stationery", 10, "0.50")
        self.assertEqual(len(self.manager.search("PEN")), 1)
        self.assertEqual(len(self.manager.search("stationery")), 1)
        self.assertEqual(self.manager.search("banana"), [])

    def test_07_update_record_and_reload(self):
        self.manager.add("Notebook", "Stationery", 10, "2.00")
        self.manager.update("P001", quantity=7, price="2.50")
        restored = InventoryManager(InventoryStorage(self.path)).get("P001")
        self.assertEqual((restored.quantity, str(restored.price)), (7, "2.50"))

    def test_08_delete_cancellation_then_confirmation(self):
        self.manager.add("Notebook", "Stationery", 10, "2.00")
        log = []
        answers = iter(["P001", "no"])
        self.assertFalse(delete_product(self.manager, ask=lambda _: next(answers), write=log.append))
        self.assertEqual(len(self.manager.list_products()), 1)
        answers = iter(["P001", "YES"])
        self.assertTrue(delete_product(self.manager, ask=lambda _: next(answers), write=log.append))
        self.assertEqual(self.manager.list_products(), [])
        self.assertEqual(InventoryManager(InventoryStorage(self.path)).list_products(), [])

    def test_09_unknown_id_handled(self):
        with self.assertRaises(ProductNotFound):
            self.manager.update("P999", name="Something")
        with self.assertRaises(ProductNotFound):
            self.manager.delete("P999")

    def test_10_json_damage_is_preserved(self):
        damaged = '{"products": ['
        self.path.write_text(damaged, encoding="utf-8")
        with self.assertRaises(DataFileError):
            InventoryManager(InventoryStorage(self.path))
        self.assertEqual(self.path.read_text(encoding="utf-8"), damaged)

    def test_11_invalid_record_shape_is_preserved(self):
        damaged = json.dumps({"version": 1, "next_id": 2, "products": [{"id": "P001", "name": "Pen"}]})
        self.path.write_text(damaged, encoding="utf-8")
        with self.assertRaises(DataFileError):
            InventoryManager(InventoryStorage(self.path))
        self.assertEqual(self.path.read_text(encoding="utf-8"), damaged)

    def test_12_summary_is_correct(self):
        self.manager.add("Notebook", "Stationery", 2, "3.50")
        self.manager.add("Pen", "Stationery", 10, "1.20")
        self.manager.add("Pencil", "Stationery", 0, "2.00")
        result = self.manager.summary()
        self.assertEqual(result["total_products"], 3)
        self.assertEqual(result["total_units"], 12)
        self.assertEqual(result["low_stock_count"], 2)
        self.assertEqual(result["inventory_value"], "19.00")

    def test_13_ids_stay_unique_after_deletion(self):
        self.manager.add("A", "Food", 2, 1)
        self.manager.add("B", "Food", 2, 1)
        self.manager.delete("P002")
        new = self.manager.add("C", "Food", 2, 1)
        self.assertEqual(new.id, "P003")
        self.assertEqual(InventoryManager(InventoryStorage(self.path)).get("P003").name, "C")

    def test_14_failed_save_does_not_apply_change(self):
        self.manager.add("Notebook", "Stationery", 5, "1.00")
        original_save = self.manager.storage.save
        self.manager.storage.save = Mock(side_effect=DataFileError("Disk full"))
        try:
            with self.assertRaises(DataFileError):
                self.manager.update("P001", quantity=100)
        finally:
            self.manager.storage.save = original_save
        self.assertEqual(self.manager.get("P001").quantity, 5)
        self.assertEqual(InventoryManager(InventoryStorage(self.path)).get("P001").quantity, 5)

    def test_15_sample_has_ten_fictional_records(self):
        sample = InventoryManager(InventoryStorage(SAMPLE))
        result = sample.summary()
        self.assertEqual(result["total_products"], 10)
        self.assertEqual(result["total_units"], 145)
        self.assertEqual(result["low_stock_count"], 3)
        self.assertEqual(result["inventory_value"], "349.30")

    def test_16_custom_product_id_and_duplicate_rejection(self):
        created = self.manager.add("Tea", "Drinks", 3, "1.25", product_id="p017")
        self.assertEqual(created.id, "P017")
        with self.assertRaisesRegex(InventoryError, "already exists"):
            self.manager.add("Other tea", "Drinks", 1, "1.00", product_id="P017")
        generated = self.manager.add("Coffee", "Drinks", 1, "2.00")
        self.assertEqual(generated.id, "P018")
        self.assertEqual(InventoryManager(InventoryStorage(self.path)).get("P017").name, "Tea")

    def test_17_low_stock_limit_can_be_configured(self):
        self.manager.add("Tea", "Drinks", 3, "1.00")
        configured = InventoryManager(InventoryStorage(self.path), low_stock_limit=2)
        self.assertEqual(configured.summary()["low_stock_count"], 0)
        self.assertEqual(configured.summary()["low_stock_limit"], 2)
        with self.assertRaises(ValueError):
            InventoryManager(InventoryStorage(self.path), low_stock_limit=-1)

    def test_18_summary_includes_stockout_and_category_breakdown(self):
        self.manager.add("Pencil", "Stationery", 3, "0.50")
        self.manager.add("Notebook", "Stationery", 0, "2.00")
        self.manager.add("Milk", "Food & Drinks", 8, "1.25")
        result = self.manager.summary()
        self.assertEqual(result["out_of_stock_count"], 1)
        self.assertEqual(result["category_breakdown"]["Stationery"]["products"], 2)
        self.assertEqual(result["category_breakdown"]["Stationery"]["units"], 3)
        self.assertEqual(result["category_breakdown"]["Stationery"]["inventory_value"], "1.50")

    def test_19_generated_id_counter_respects_existing_records_and_persists(self):
        payload = {
            "version": 1,
            "next_id": 4,
            "products": [
                {"id": "P001", "name": "First", "category": "Other", "quantity": 1, "price": "1.00"},
                {"id": "P003", "name": "Third", "category": "Other", "quantity": 1, "price": "1.00"},
            ],
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        restored = InventoryManager(InventoryStorage(self.path))
        added = restored.add("Fourth", "Other", 1, "1.00")
        self.assertEqual(added.id, "P004")
        after_restart = InventoryManager(InventoryStorage(self.path))
        self.assertEqual(after_restart.get("P004").name, "Fourth")


if __name__ == "__main__":
    unittest.main()

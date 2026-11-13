"""Inventory application logic: Python classes, collections, and validation.

This module deliberately does not import web or command-line dependencies.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Optional

from storage import DataFileError, InventoryStorage


LOW_STOCK_LIMIT = 5
MAX_QUANTITY = 1_000_000
MAX_PRICE = Decimal("999999.99")


class InventoryError(ValueError):
    """An inventory operation was rejected without changing stored data."""


class ProductNotFound(InventoryError):
    """The requested product ID does not exist."""


def _text(value, field, length):
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"{field} is required.")
    cleaned = value.strip()
    if len(cleaned) > length:
        raise InventoryError(f"{field} must have at most {length} characters.")
    return cleaned


def _quantity(value):
    if isinstance(value, bool):
        raise InventoryError("Quantity must be a whole number from 0 to 1,000,000.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,7}", value.strip()):
        number = int(value.strip())
    else:
        raise InventoryError("Quantity must be a whole number from 0 to 1,000,000.")
    if not 0 <= number <= MAX_QUANTITY:
        raise InventoryError("Quantity must be a whole number from 0 to 1,000,000.")
    return number


def _price(value):
    # Only plain decimal money values with up to two digits after the point.
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise InventoryError("Price must be a non-negative number with at most 2 decimals.")
    raw = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,2})?", raw):
        raise InventoryError("Price must be a non-negative number with at most 2 decimals.")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise InventoryError("Price must be a non-negative number with at most 2 decimals.") from None
    if amount > MAX_PRICE:
        raise InventoryError("Price must be a non-negative number with at most 2 decimals.")
    return amount.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class Product:
    """A single inventory record with validated fields."""

    id: str
    name: str
    category: str
    quantity: int
    price: Decimal

    @classmethod
    def create(cls, product_id, name, category, quantity, price):
        if not isinstance(product_id, str) or not re.fullmatch(r"P[0-9]{3,}", product_id):
            raise InventoryError("Product ID must look like P001.")
        return cls(
            id=product_id,
            name=_text(name, "Item name", 80),
            category=_text(category, "Category", 40),
            quantity=_quantity(quantity),
            price=_price(price),
        )

    @classmethod
    def from_dict(cls, row):
        if not isinstance(row, dict):
            raise InventoryError("A product record must be a JSON object.")
        try:
            return cls.create(row["id"], row["name"], row["category"], row["quantity"], row["price"])
        except KeyError as exc:
            raise InventoryError(f"A product record is missing field {exc.args[0]}.") from None

    def to_dict(self):
        # Decimal is stored as a string to avoid floating-point rounding errors.
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "quantity": self.quantity,
            "price": str(self.price),
        }

    @property
    def stock_value(self):
        return self.price * self.quantity


class InventoryManager:
    """Controls records, searching, summaries, and saving completed changes."""

    def __init__(self, storage: InventoryStorage, low_stock_limit=LOW_STOCK_LIMIT):
        if isinstance(low_stock_limit, bool) or not isinstance(low_stock_limit, int) or low_stock_limit < 0:
            raise ValueError("Low-stock limit must be a non-negative whole number.")
        self.storage = storage
        self.low_stock_limit = low_stock_limit
        data = storage.load()
        records = {}
        for index, row in enumerate(data["products"], start=1):
            try:
                product = Product.from_dict(row)
                if product.id in records:
                    raise InventoryError(f"Duplicate product ID {product.id}.")
                records[product.id] = product
            except InventoryError as exc:
                raise DataFileError(
                    f"Invalid product #{index} in {storage.path}: {exc} "
                    "The original data file was not changed."
                ) from exc
        highest = max((int(pid[1:]) for pid in records), default=0)
        if data["next_id"] <= highest:
            raise DataFileError(
                f"Invalid next_id in {storage.path}. The original data file was not changed."
            )
        self._products = records  # Dictionary: unique-ID lookup is quick and simple.
        self._next_id = data["next_id"]

    def _commit(self, products, next_id):
        payload = {
            "version": 1,
            "next_id": next_id,
            "products": [record.to_dict() for record in products.values()],
        }
        # Only modify in-memory state after save succeeds.
        self.storage.save(payload)
        self._products = products
        self._next_id = next_id

    def list_products(self):
        return list(self._products.values())

    def get(self, product_id):
        product = self._products.get(str(product_id).strip().upper())
        if product is None:
            raise ProductNotFound(f"Product '{product_id}' was not found.")
        return product

    def add(self, name, category, quantity, price, product_id=None, *, idempotency_key=None):
        """Add a product, generating an ID unless one is explicitly supplied."""
        # Accepted to share the storage-adapter API; JSON writes already happen
        # once per confirmed bot callback and need no database idempotency key.
        del idempotency_key
        next_id = self._next_id
        if product_id is None:
            while f"P{next_id:03d}" in self._products:
                next_id += 1
            product_id = f"P{next_id:03d}"
            next_id += 1
        else:
            product_id = str(product_id).strip().upper()
            if not re.fullmatch(r"P[0-9]{3,}", product_id):
                raise InventoryError("Product ID must look like P001.")
            if product_id in self._products:
                raise InventoryError(f"Product ID '{product_id}' already exists.")
            # Keep the persisted sequence above every numeric ID so the file
            # remains valid and future automatically generated IDs stay unique.
            next_id = max(next_id, int(product_id[1:]) + 1)
        product = Product.create(product_id, name, category, quantity, price)
        updated = self._products.copy()
        updated[product.id] = product
        self._commit(updated, next_id)
        return product

    def update(self, product_id, *, name=None, category=None, quantity=None, price=None):
        original = self.get(product_id)
        if all(value is None for value in (name, category, quantity, price)):
            raise InventoryError("Provide at least one field to update.")
        replacement = Product.create(
            original.id,
            original.name if name is None else name,
            original.category if category is None else category,
            original.quantity if quantity is None else quantity,
            original.price if price is None else price,
        )
        updated = self._products.copy()
        updated[original.id] = replacement
        self._commit(updated, self._next_id)
        return replacement

    def delete(self, product_id):
        original = self.get(product_id)
        updated = self._products.copy()
        del updated[original.id]
        self._commit(updated, self._next_id)
        return original

    def search(self, query):
        needle = str(query).strip().casefold()
        return [
            product for product in self._products.values()
            if needle in product.id.casefold()
            or needle in product.name.casefold()
            or needle in product.category.casefold()
        ]

    def summary(self):
        products = self.list_products()
        categories = {}
        for item in products:
            category = categories.setdefault(item.category, {
                "products": 0,
                "units": 0,
                "inventory_value": Decimal("0.00"),
            })
            category["products"] += 1
            category["units"] += item.quantity
            category["inventory_value"] += item.stock_value
        return {
            "total_products": len(products),
            "total_units": sum(item.quantity for item in products),
            "low_stock_count": sum(item.quantity <= self.low_stock_limit for item in products),
            "out_of_stock_count": sum(item.quantity == 0 for item in products),
            "inventory_value": str(sum((item.stock_value for item in products), Decimal("0.00"))),
            "low_stock_limit": self.low_stock_limit,
            "category_breakdown": {
                name: {
                    **values,
                    "inventory_value": str(values["inventory_value"]),
                }
                for name, values in categories.items()
            },
        }

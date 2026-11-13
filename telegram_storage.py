"""Separate local JSON inventory files for each private Telegram account."""

from pathlib import Path

from inventory import InventoryError, InventoryManager
from storage import InventoryStorage


MAX_PRODUCTS_PER_USER = 500


class UserInventory:
    """Inventory facade bound to one verified Telegram user ID."""

    def __init__(self, path, low_stock_limit):
        self.path = Path(path)
        self._manager = InventoryManager(InventoryStorage(self.path), low_stock_limit)

    def __getattr__(self, name):
        return getattr(self._manager, name)

    def ensure_account(self):
        if not self.path.exists():
            self._manager.storage.save({"version": 1, "next_id": 1, "products": []})

    def add(self, name, category, quantity, price, product_id=None, *, idempotency_key=None):
        if len(self._manager.list_products()) >= MAX_PRODUCTS_PER_USER:
            raise InventoryError(f"Each account can store up to {MAX_PRODUCTS_PER_USER} products.")
        return self._manager.add(
            name, category, quantity, price, product_id, idempotency_key=idempotency_key,
        )

    def delete_account(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True


class LocalTelegramInventoryManager:
    """Resolve private Telegram IDs to distinct, ignored local JSON files."""

    def __init__(self, directory, low_stock_limit=5):
        if isinstance(low_stock_limit, bool) or not isinstance(low_stock_limit, int) or low_stock_limit < 0:
            raise ValueError("Low-stock limit must be a non-negative whole number.")
        self.directory = Path(directory)
        self.low_stock_limit = low_stock_limit

    def for_user(self, user_id):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("A verified Telegram user ID is required")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        return UserInventory(self.directory / f"{user_id}.json", self.low_stock_limit)

"""User-scoped PostgreSQL inventory adapter for the public Telegram service.

The CLI continues to use ``InventoryStorage`` and local JSON. This adapter uses
the server-side PostgreSQL connection string and scopes every product query to
the verified Telegram account ID.
"""

from decimal import Decimal
import re

from inventory import InventoryError, Product, ProductNotFound, _price, _quantity, _text


MAX_PRODUCTS_PER_USER = 500


class PostgresInventoryManager:
    low_stock_limit = 5

    def __init__(self, database_url, low_stock_limit=5, connect=None, ssl_root_cert=None):
        if not database_url or not str(database_url).strip():
            raise ValueError("DATABASE_URL is required for PostgreSQL storage")
        if isinstance(low_stock_limit, bool) or not isinstance(low_stock_limit, int) or low_stock_limit < 0:
            raise ValueError("Low-stock limit must be a non-negative whole number.")
        self.database_url = str(database_url)
        self.low_stock_limit = low_stock_limit
        self.ssl_root_cert = str(ssl_root_cert) if ssl_root_cert else None
        if connect is None:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("PostgreSQL support is missing; install requirements.txt") from exc
            connect = psycopg.connect
        self._connect = connect

    def for_user(self, user_id):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("A verified Telegram user ID is required")
        return UserInventory(self, user_id)

    def check_connection(self):
        with self._connect(self.database_url, **self._connection_options()) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            if cur.fetchone()[0] != 1:
                return False
            # Also fail startup if the migration has not been applied or this
            # role lacks table access; RLS intentionally returns no user rows.
            cur.execute("SELECT count(*) FROM public.shop_users")
            cur.fetchone()
            cur.execute("SELECT count(*) FROM public.shop_products")
            cur.fetchone()
            return True

    def _connection(self, user_id):
        conn = self._connect(self.database_url, **self._connection_options())
        # Transaction-local identity is used by RLS policies on the dedicated
        # non-owner application role. Always set it from verified Telegram data.
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.telegram_user_id', %s, true)", (str(user_id),))
        except Exception:
            conn.close()
            raise
        return conn

    def _connection_options(self):
        options = {"connect_timeout": 10, "sslmode": "verify-full"}
        if self.ssl_root_cert:
            options["sslrootcert"] = self.ssl_root_cert
        return options


class UserInventory:
    """Inventory facade bound to one verified numeric account ID."""

    def __init__(self, store, user_id):
        self.store = store
        self.user_id = user_id
        self.low_stock_limit = store.low_stock_limit

    def ensure_account(self):
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.shop_users (telegram_user_id) VALUES (%s) "
                "ON CONFLICT (telegram_user_id) DO NOTHING",
                (self.user_id,),
            )

    @staticmethod
    def _product(row):
        return Product.create(row[0], row[1], row[2], row[3], row[4])

    def list_products(self):
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT product_id, name, category, quantity, price "
                "FROM public.shop_products WHERE telegram_user_id = %s "
                "ORDER BY substring(product_id from 2)::bigint",
                (self.user_id,),
            )
            return [self._product(row) for row in cur.fetchall()]

    def get(self, product_id):
        normalized = str(product_id).strip().upper()
        if not re.fullmatch(r"P[0-9]{3,}", normalized):
            raise ProductNotFound(f"Product '{product_id}' was not found.")
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT product_id, name, category, quantity, price FROM public.shop_products "
                "WHERE telegram_user_id = %s AND product_id = %s",
                (self.user_id, normalized),
            )
            row = cur.fetchone()
        if row is None:
            raise ProductNotFound(f"Product '{product_id}' was not found.")
        return self._product(row)

    def add(self, name, category, quantity, price, product_id=None, *, idempotency_key=None):
        name, category = _text(name, "Item name", 80), _text(category, "Category", 40)
        quantity, price = _quantity(quantity), _price(price)
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", idempotency_key):
                raise InventoryError("Invalid request reference.")
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.shop_users (telegram_user_id) VALUES (%s) "
                "ON CONFLICT (telegram_user_id) DO NOTHING",
                (self.user_id,),
            )
            cur.execute(
                "SELECT next_product_number FROM public.shop_users "
                "WHERE telegram_user_id = %s FOR UPDATE",
                (self.user_id,),
            )
            sequence = cur.fetchone()[0]
            if idempotency_key is not None:
                cur.execute(
                    "SELECT product_id, name, category, quantity, price FROM public.shop_products "
                    "WHERE telegram_user_id = %s AND idempotency_key = %s",
                    (self.user_id, idempotency_key),
                )
                existing = cur.fetchone()
                if existing:
                    return self._product(existing)
            cur.execute(
                "SELECT count(*) FROM public.shop_products WHERE telegram_user_id = %s",
                (self.user_id,),
            )
            if cur.fetchone()[0] >= MAX_PRODUCTS_PER_USER:
                raise InventoryError(f"Each account can store up to {MAX_PRODUCTS_PER_USER} products.")
            if product_id is None:
                product_id = f"P{sequence:03d}"
            else:
                product_id = str(product_id).strip().upper()
                if not re.fullmatch(r"P[0-9]{3,}", product_id):
                    raise InventoryError("Product ID must look like P001.")
            product = Product.create(product_id, name, category, quantity, price)
            cur.execute(
                "INSERT INTO public.shop_products "
                "(telegram_user_id, product_id, name, category, quantity, price, idempotency_key) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (telegram_user_id, idempotency_key) DO NOTHING "
                "RETURNING product_id, name, category, quantity, price",
                (self.user_id, product.id, product.name, product.category, product.quantity, product.price, idempotency_key),
            )
            row = cur.fetchone()
            if row is None and idempotency_key is not None:
                cur.execute(
                    "SELECT product_id, name, category, quantity, price FROM public.shop_products "
                    "WHERE telegram_user_id = %s AND idempotency_key = %s",
                    (self.user_id, idempotency_key),
                )
                row = cur.fetchone()
            if row is None:
                raise InventoryError("That product ID already exists in your inventory.")
            cur.execute(
                "UPDATE public.shop_users SET next_product_number = GREATEST(next_product_number, %s) "
                "WHERE telegram_user_id = %s",
                (int(product.id[1:]) + 1, self.user_id),
            )
            return self._product(row)

    def update(self, product_id, *, name=None, category=None, quantity=None, price=None):
        if all(value is None for value in (name, category, quantity, price)):
            raise InventoryError("Provide at least one field to update.")
        original = self.get(product_id)
        product = Product.create(
            original.id,
            original.name if name is None else name,
            original.category if category is None else category,
            original.quantity if quantity is None else quantity,
            original.price if price is None else price,
        )
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE public.shop_products SET name = %s, category = %s, quantity = %s, price = %s, "
                "updated_at = now() WHERE telegram_user_id = %s AND product_id = %s "
                "RETURNING product_id, name, category, quantity, price",
                (product.name, product.category, product.quantity, product.price, self.user_id, product.id),
            )
            row = cur.fetchone()
        if row is None:
            raise ProductNotFound(f"Product '{product_id}' was not found.")
        return self._product(row)

    def delete(self, product_id):
        original = self.get(product_id)
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM public.shop_products WHERE telegram_user_id = %s AND product_id = %s "
                "RETURNING product_id",
                (self.user_id, original.id),
            )
            if cur.fetchone() is None:
                raise ProductNotFound(f"Product '{product_id}' was not found.")
        return original

    def search(self, query):
        needle = str(query).strip()
        if not needle:
            return []
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT product_id, name, category, quantity, price FROM public.shop_products "
                "WHERE telegram_user_id = %s AND (product_id ILIKE %s ESCAPE E'\\\\' "
                "OR name ILIKE %s ESCAPE E'\\\\' OR category ILIKE %s ESCAPE E'\\\\') "
                "ORDER BY substring(product_id from 2)::bigint",
                (self.user_id, f"%{escaped}%", f"%{escaped}%", f"%{escaped}%"),
            )
            return [self._product(row) for row in cur.fetchall()]

    def summary(self):
        products = self.list_products()
        categories = {}
        for item in products:
            row = categories.setdefault(item.category, {"products": 0, "units": 0, "inventory_value": Decimal("0.00")})
            row["products"] += 1
            row["units"] += item.quantity
            row["inventory_value"] += item.stock_value
        return {
            "total_products": len(products),
            "total_units": sum(p.quantity for p in products),
            "low_stock_count": sum(p.quantity <= self.low_stock_limit for p in products),
            "out_of_stock_count": sum(p.quantity == 0 for p in products),
            "inventory_value": str(sum((p.stock_value for p in products), Decimal("0.00"))),
            "low_stock_limit": self.low_stock_limit,
            "category_breakdown": {
                name: {**values, "inventory_value": str(values["inventory_value"])}
                for name, values in categories.items()
            },
        }

    def delete_account(self):
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            # Webhook delivery records do not reference shop_users, so remove this
            # user's deduplication state explicitly as part of the same transaction.
            cur.execute(
                "DELETE FROM public.shop_webhook_updates WHERE telegram_user_id = %s",
                (self.user_id,),
            )
            cur.execute(
                "DELETE FROM public.shop_users WHERE telegram_user_id = %s RETURNING telegram_user_id",
                (self.user_id,),
            )
            return cur.fetchone() is not None

    def consume_rate_limit(self, limit=60):
        """Atomically charge one request against a persistent 60-second window."""
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.shop_rate_limits (telegram_user_id, window_started_at, request_count) "
                "VALUES (%s, now(), 1) "
                "ON CONFLICT (telegram_user_id) DO UPDATE SET "
                "window_started_at = CASE "
                "WHEN public.shop_rate_limits.window_started_at <= now() - interval '60 seconds' "
                "THEN now() ELSE public.shop_rate_limits.window_started_at END, "
                "request_count = CASE "
                "WHEN public.shop_rate_limits.window_started_at <= now() - interval '60 seconds' "
                "THEN 1 ELSE public.shop_rate_limits.request_count + 1 END, "
                "updated_at = now() RETURNING request_count",
                (self.user_id,),
            )
            return cur.fetchone()[0] <= limit

    def claim_webhook_update(self, update_id, retry_after_seconds=300):
        """Claim an update once; return claimed, duplicate, or busy."""
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM public.shop_webhook_updates "
                "WHERE telegram_user_id = %s AND received_at < now() - interval '30 days'",
                (self.user_id,),
            )
            cur.execute(
                "INSERT INTO public.shop_webhook_updates (update_id, telegram_user_id, status) "
                "VALUES (%s, %s, 'processing') ON CONFLICT (update_id) DO NOTHING RETURNING update_id",
                (update_id, self.user_id),
            )
            if cur.fetchone() is not None:
                return "claimed"
            cur.execute(
                "SELECT status, started_at FROM public.shop_webhook_updates "
                "WHERE update_id = %s AND telegram_user_id = %s FOR UPDATE",
                (update_id, self.user_id),
            )
            existing = cur.fetchone()
            if existing is None or existing[0] == "done":
                return "duplicate"
            if existing[0] == "processing":
                cur.execute(
                    "SELECT %s::timestamptz > now() - (%s * interval '1 second')",
                    (existing[1], retry_after_seconds),
                )
                if cur.fetchone()[0]:
                    return "busy"
            cur.execute(
                "UPDATE public.shop_webhook_updates SET status='processing', started_at=now(), "
                "attempts=attempts+1, finished_at=NULL WHERE update_id=%s AND telegram_user_id=%s",
                (update_id, self.user_id),
            )
            return "claimed"

    def finish_webhook_update(self, update_id, *, succeeded):
        status = "done" if succeeded else "failed"
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE public.shop_webhook_updates SET status=%s, finished_at=now() "
                "WHERE update_id=%s AND telegram_user_id=%s",
                (status, update_id, self.user_id),
            )

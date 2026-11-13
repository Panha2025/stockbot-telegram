"""Unit tests for PostgreSQL query scoping without using a real database."""
import unittest

from inventory import ProductNotFound
from postgres_storage import MAX_PRODUCTS_PER_USER, PostgresInventoryManager


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        self.connection.calls.append((" ".join(sql.split()), params))
        if "set_config" in sql:
            self.connection.identity = params[0]
        elif sql.startswith("INSERT INTO public.shop_users") or sql.startswith("UPDATE public.shop_users"):
            self.row = None
        elif self.connection.answers:
            self.row = self.connection.answers.pop(0)
        else:
            self.row = None

    def fetchone(self):
        return self.row

    def fetchall(self):
        if self.row is None:
            return []
        return self.row if isinstance(self.row, list) else [self.row]


class FakeConnection:
    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls = []
        self.identity = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return FakeCursor(self)


class PostgresStorageTests(unittest.TestCase):
    def setUp(self):
        self.connections = []

        def connect(*_args, **_kwargs):
            conn = FakeConnection(self.answers.pop(0) if self.answers else ())
            self.connections.append(conn)
            return conn

        self.answers = []
        self.store = PostgresInventoryManager("postgresql://unit-test.invalid/db", connect=connect)

    def test_user_binding_is_required_and_positive(self):
        with self.assertRaises(ValueError):
            self.store.for_user(0)
        with self.assertRaises(ValueError):
            self.store.for_user(True)

    def test_connections_require_full_tls_verification_and_optional_root_certificate(self):
        self.assertEqual(
            self.store._connection_options(),
            {"connect_timeout": 10, "sslmode": "verify-full"},
        )
        with_certificate = PostgresInventoryManager(
            "postgresql://unit-test.invalid/db",
            connect=lambda *_args, **_kwargs: FakeConnection(),
            ssl_root_cert="/etc/secrets/supabase-ca.crt",
        )
        self.assertEqual(
            with_certificate._connection_options(),
            {
                "connect_timeout": 10,
                "sslmode": "verify-full",
                "sslrootcert": "/etc/secrets/supabase-ca.crt",
            },
        )

    def test_product_lookup_is_scoped_and_uses_transaction_local_rls_identity(self):
        self.answers = [[("P001", "Pen", "Stationery", 2, "0.50")]]
        product = self.store.for_user(71234).get("P001")
        self.assertEqual(product.name, "Pen")
        conn = self.connections[-1]
        self.assertEqual(conn.identity, "71234")
        query, params = conn.calls[-1]
        self.assertIn("WHERE telegram_user_id = %s AND product_id = %s", query)
        self.assertEqual(params, (71234, "P001"))

    def test_guessed_product_id_is_not_found_for_another_account(self):
        self.answers = [[None]]
        with self.assertRaises(ProductNotFound):
            self.store.for_user(81234).get("P001")
        self.assertEqual(self.connections[-1].identity, "81234")

    def test_two_accounts_receive_separately_scoped_inventory_queries(self):
        self.answers = [[("P001", "A item", "Other", 1, "1.00")], []]
        self.assertEqual(self.store.for_user(11).list_products()[0].name, "A item")
        self.assertEqual(self.store.for_user(22).list_products(), [])
        self.assertEqual(self.connections[0].calls[-1][1], (11,))
        self.assertEqual(self.connections[1].calls[-1][1], (22,))
        self.assertEqual([conn.identity for conn in self.connections], ["11", "22"])

    def test_search_sql_is_parameterized_and_owner_scoped(self):
        self.answers = [[]]
        self.assertEqual(self.store.for_user(31).search("%_ OR 1=1"), [])
        query, params = self.connections[-1].calls[-1]
        self.assertIn("WHERE telegram_user_id = %s", query)
        self.assertEqual(params[0], 31)
        self.assertNotIn("OR 1=1", query)
        self.assertIn("\\%\\_ OR 1=1", params[1])

    def test_duplicate_confirmation_returns_existing_product_without_second_insert(self):
        self.answers = [[(1,), ("P001", "Pen", "Stationery", 3, "0.50")]]
        product = self.store.for_user(41).add(
            "Pen", "Stationery", 3, "0.50", idempotency_key="tap_again",
        )
        self.assertEqual(product.id, "P001")
        self.assertFalse(any(query.startswith("INSERT INTO public.shop_products") for query, _ in self.connections[-1].calls))

    def test_invalid_product_input_fails_before_database_access(self):
        with self.assertRaises(ValueError):
            self.store.for_user(51).add("", "Other", 1, "1.00")
        self.assertEqual(self.connections, [])

    def test_connection_failure_is_propagated_for_safe_handler_reporting(self):
        def unavailable(*_args, **_kwargs):
            raise OSError("private connection detail")
        store = PostgresInventoryManager("postgresql://unit-test.invalid/db", connect=unavailable)
        with self.assertRaisesRegex(OSError, "private connection detail"):
            store.for_user(61).list_products()

    def test_add_is_transaction_scoped_decimal_and_idempotent(self):
        self.answers = [[(1,), None, (0,), ("P001", "Pen", "Stationery", 3, "0.50")]]
        product = self.store.for_user(91234).add(
            "Pen", "Stationery", "3", "0.50", idempotency_key="confirm_1",
        )
        self.assertEqual((product.id, str(product.price)), ("P001", "0.50"))
        conn = self.connections[-1]
        self.assertEqual(conn.identity, "91234")
        sql = "\n".join(query for query, _ in conn.calls)
        self.assertIn("FOR UPDATE", sql)
        inserts = [(query, params) for query, params in conn.calls if query.startswith("INSERT INTO public.shop_products")]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][1][0], 91234)
        self.assertEqual(inserts[0][1][-1], "confirm_1")
        self.assertEqual(inserts[0][1][-2], product.price)

    def test_account_delete_is_scoped_to_verified_user(self):
        self.answers = [[(101010,)]]
        self.assertTrue(self.store.for_user(101010).delete_account())
        query, params = self.connections[-1].calls[-1]
        self.assertIn("DELETE FROM public.shop_users WHERE telegram_user_id = %s", query)
        self.assertEqual(params, (101010,))

    def test_product_limit_is_a_server_side_guard(self):
        self.assertEqual(MAX_PRODUCTS_PER_USER, 500)

    def test_webhook_update_claim_is_unique_and_completed_redelivery_is_duplicate(self):
        self.answers = [[None, (1234,)], [None, None, ("done", None)]]
        scoped = self.store.for_user(7001)
        self.assertEqual(scoped.claim_webhook_update(1234), "claimed")
        self.assertEqual(scoped.claim_webhook_update(1234), "duplicate")
        for conn in self.connections:
            self.assertEqual(conn.identity, "7001")
            self.assertTrue(any("ON CONFLICT (update_id) DO NOTHING" in query for query, _ in conn.calls))

    def test_recent_in_progress_update_returns_busy_for_telegram_retry(self):
        self.answers = [[None, None, ("processing", "2026-11-13T00:00:00Z"), (True,)]]
        self.assertEqual(self.store.for_user(7002).claim_webhook_update(1235), "busy")
        self.assertTrue(any("FOR UPDATE" in query for query, _ in self.connections[-1].calls))

    def test_failed_update_can_be_reclaimed(self):
        self.answers = [[None, None, ("failed", None)]]
        self.assertEqual(self.store.for_user(7003).claim_webhook_update(1236), "claimed")
        self.assertTrue(any("attempts=attempts+1" in query for query, _ in self.connections[-1].calls))

    def test_persistent_rate_limit_uses_server_returned_count(self):
        self.answers = [[(60,)], [(61,)]]
        scoped = self.store.for_user(7004)
        self.assertTrue(scoped.consume_rate_limit())
        self.assertFalse(scoped.consume_rate_limit())
        self.assertTrue(all(conn.identity == "7004" for conn in self.connections))


if __name__ == "__main__":
    unittest.main()

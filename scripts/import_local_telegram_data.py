"""Optionally copy ignored local Telegram JSON inventories into Supabase.

The default is a read-only dry run. --apply performs one all-or-nothing
transaction and refuses the entire import if any target Telegram account
already exists in Postgres. Source files are never modified or removed.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from bot_helpers import load_env_file, resolve_config_value
from inventory import InventoryManager
from postgres_storage import MAX_PRODUCTS_PER_USER, PostgresInventoryManager
from storage import InventoryStorage
from telegram_bot import BASE


DATA_DIRECTORY = BASE / "data" / "telegram_users"
MAX_BIGINT = 9_223_372_036_854_775_807


@dataclass(frozen=True)
class LocalAccount:
    user_id: int
    next_product_number: int
    products: tuple


def read_local_accounts(directory=DATA_DIRECTORY):
    """Validate source JSON while keeping its contents out of CLI output."""
    directory = Path(directory)
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError("The private Telegram inventory directory is not a folder.")

    accounts = []
    for path in sorted(directory.glob("*.json")):
        if not re.fullmatch(r"[1-9][0-9]{0,18}", path.stem):
            raise ValueError("A private Telegram inventory filename is invalid.")
        user_id = int(path.stem)
        if user_id > MAX_BIGINT:
            raise ValueError("A Telegram account ID is outside the supported range.")
        manager = InventoryManager(InventoryStorage(path))
        products = tuple(manager.list_products())
        if len(products) > MAX_PRODUCTS_PER_USER:
            raise ValueError("A local account exceeds the product limit.")
        accounts.append(LocalAccount(user_id, manager._next_id, products))
    return accounts


def _ensure_targets_empty(cursor, accounts):
    for account in accounts:
        cursor.execute(
            "SELECT 1 FROM public.shop_users WHERE telegram_user_id = %s",
            (account.user_id,),
        )
        if cursor.fetchone() is not None:
            raise RuntimeError(
                "At least one target account already exists in Supabase; no data was imported. "
                "Resolve the conflict manually before retrying."
            )


def import_accounts(store, accounts, *, apply=False):
    """Check for conflicts and optionally copy every source account atomically."""
    with store._connect(store.database_url, **store._connection_options()) as connection:
        with connection.cursor() as cursor:
            # Preflight every destination before writing anything. RLS is still
            # active; the app identity changes only to the verified file ID.
            for account in accounts:
                cursor.execute(
                    "SELECT set_config('app.telegram_user_id', %s, true)",
                    (str(account.user_id),),
                )
                cursor.execute(
                    "SELECT 1 FROM public.shop_users WHERE telegram_user_id = %s",
                    (account.user_id,),
                )
                if cursor.fetchone() is not None:
                    raise RuntimeError(
                        "At least one target account already exists in Supabase; no data was imported. "
                        "Resolve the conflict manually before retrying."
                    )
            if not apply:
                connection.rollback()
                return sum(len(account.products) for account in accounts)

            for account in accounts:
                cursor.execute(
                    "SELECT set_config('app.telegram_user_id', %s, true)",
                    (str(account.user_id),),
                )
                cursor.execute(
                    "INSERT INTO public.shop_users (telegram_user_id, next_product_number) "
                    "VALUES (%s, %s)",
                    (account.user_id, account.next_product_number),
                )
                for product in account.products:
                    cursor.execute(
                        "INSERT INTO public.shop_products "
                        "(telegram_user_id, product_id, name, category, quantity, price) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (
                            account.user_id, product.id, product.name,
                            product.category, product.quantity, product.price,
                        ),
                    )
    return sum(len(account.products) for account in accounts)


def _database_store():
    config = load_env_file(BASE / ".env")
    database_url, _ = resolve_config_value("DATABASE_URL", config)
    cert_name, _ = resolve_config_value("DATABASE_SSL_ROOT_CERT", config)
    if not database_url:
        raise ValueError("Set DATABASE_URL privately in .env before importing.")
    if not cert_name:
        raise ValueError("Set DATABASE_SSL_ROOT_CERT to the private Supabase root certificate path in .env.")
    cert_path = Path(cert_name).expanduser()
    if not cert_path.is_absolute():
        cert_path = BASE / cert_path
    if not cert_path.is_file():
        raise ValueError("The configured private Supabase root certificate was not found.")
    return PostgresInventoryManager(database_url, ssl_root_cert=cert_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="write after preflighting every account; the transaction aborts if any target already exists",
    )
    args = parser.parse_args(argv)
    try:
        accounts = read_local_accounts()
        if not accounts:
            print("No local Telegram inventory files were found; nothing to import.")
            return 0
        products = sum(len(account.products) for account in accounts)
        store = _database_store()
        imported = import_accounts(store, accounts, apply=args.apply)
    except Exception as exc:
        # Exception text from JSON/DB drivers can include private paths or data.
        print(f"Import stopped safely ({type(exc).__name__}); source files were not changed.")
        return 1

    if args.apply:
        print(f"Imported {len(accounts)} private inventory files and {imported} products. Local files were preserved.")
    else:
        print(
            f"Dry run passed: {len(accounts)} private inventory files and {products} products are valid; "
            "all target accounts are empty. No data was written. Re-run with --apply to import."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Menu / user interaction: COSC 221's required command-line application."""

import argparse
from pathlib import Path

from inventory import InventoryError, InventoryManager
from storage import DataFileError, InventoryStorage


DEFAULT_DATA = Path(__file__).resolve().parent / "data" / "inventory.json"


def display_products(products):
    if not products:
        print("No products found.")
        return
    print(f"{'ID':<8} {'Item name':<27} {'Category':<18} {'Qty':>6} {'Price':>11}")
    print("-" * 76)
    for item in products:
        print(f"{item.id:<8} {item.name[:27]:<27} {item.category[:18]:<18} {item.quantity:>6} ${item.price:>10}")


def ask_product():
    return {
        "name": input("Item name: ").strip(),
        "category": input("Category: ").strip(),
        "quantity": input("Quantity (0 or more): ").strip(),
        "price": input("Unit price (e.g. 3.50): ").strip(),
    }


def update_product(manager):
    product_id = input("Product ID to update: ").strip()
    current = manager.get(product_id)
    print("Leave a field blank to keep its current value.")
    name = input(f"Item name [{current.name}]: ").strip()
    category = input(f"Category [{current.category}]: ").strip()
    quantity = input(f"Quantity [{current.quantity}]: ").strip()
    price = input(f"Price [{current.price}]: ").strip()
    updated = manager.update(
        product_id,
        name=name if name else None,
        category=category if category else None,
        quantity=quantity if quantity else None,
        price=price if price else None,
    )
    print(f"Updated {updated.id}: {updated.name} (saved).")


def delete_product(manager, ask=input, write=print):
    product_id = ask("Product ID to delete: ").strip()
    product = manager.get(product_id)
    confirmation = ask(f"Delete '{product.name}' ({product.id})? Type YES to confirm: ").strip()
    if confirmation != "YES":
        write("Deletion cancelled. Nothing was changed.")
        return False
    manager.delete(product_id)
    write(f"Deleted {product.id} (saved).")
    return True


def show_summary(manager):
    result = manager.summary()
    print(f"Unique products:  {result['total_products']}")
    print(f"Units in stock:  {result['total_units']}")
    print(f"Low-stock items: {result['low_stock_count']} (quantity <= {result['low_stock_limit']})")
    print(f"Stock value:     ${result['inventory_value']}")


def run_menu(manager):
    while True:
        print("\n" + "=" * 46)
        print("  SMALL SHOP INVENTORY | COSC 221")
        print("=" * 46)
        print("1. Add a product")
        print("2. View all products")
        print("3. Search products")
        print("4. Update a product")
        print("5. Delete a product")
        print("6. Inventory summary")
        print("7. Exit")
        try:
            choice = input("Choose 1-7: ").strip()
            if choice == "1":
                product = manager.add(**ask_product())
                print(f"Added {product.id}: {product.name} (saved).")
            elif choice == "2":
                display_products(manager.list_products())
            elif choice == "3":
                query = input("Search by ID, name, or category: ")
                display_products(manager.search(query))
            elif choice == "4":
                update_product(manager)
            elif choice == "5":
                delete_product(manager)
            elif choice == "6":
                show_summary(manager)
            elif choice == "7":
                print("Goodbye! All successful changes have already been saved.")
                break
            else:
                print("Please enter a number from 1 to 7.")
        except (InventoryError, DataFileError) as exc:
            print(f"Error: {exc}")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye. Saved data is safe.")
            break


def main(argv=None):
    parser = argparse.ArgumentParser(description="Small Shop Inventory (Python CLI)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to inventory JSON")
    parser.add_argument("--low-stock-limit", type=int, default=5, help="Low-stock warning threshold (default: 5)")
    args = parser.parse_args(argv)
    if args.low_stock_limit < 0:
        parser.error("--low-stock-limit must be zero or greater")
    try:
        manager = InventoryManager(InventoryStorage(args.data), low_stock_limit=args.low_stock_limit)
    except DataFileError as exc:
        print(f"Cannot start: {exc}")
        return 1
    run_menu(manager)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

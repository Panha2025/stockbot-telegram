"""Small, testable helpers for Telegram messages and local .env configuration.

No Telegram dependency here: students can learn/test these functions with Python only.
"""

from pathlib import Path
import os
import re

PAGE_SIZE = 5


def resolve_config_value(name, file_values, aliases=(), environ=None, default=""):
    """Resolve non-empty process values first, then non-empty local .env values.

    Blank exported variables are treated as unset so they cannot accidentally
    mask a valid value in the project's .env file.
    """
    environ = os.environ if environ is None else environ
    names = (name, *aliases)
    for key in names:
        value = environ.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip(), f"environment:{key}"
    for key in names:
        value = file_values.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip(), f".env:{key}"
    return default, "default"


def load_env_file(path):
    """Load KEY=VALUE pairs. Never execute configuration as Python code."""
    result = {}
    path = Path(path)
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key.replace("_", "").isalnum():
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[key] = value
    return result


def parse_allowed_ids(raw):
    """Empty allowlist means nobody can edit the inventory."""
    if not raw.strip():
        return set()
    ids = set()
    for value in raw.split(","):
        value = value.strip()
        if not value.isdecimal() or int(value) <= 0:
            raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain positive numeric IDs separated by commas")
        ids.add(int(value))
    return ids


def is_authorized_user(user_id, chat_type, allowed_ids):
    """Only allow configured users in private chats to access inventory."""
    return chat_type == "private" and user_id is not None and user_id in allowed_ids


def parse_callback_action(data):
    """Validate callback payloads used by menus, product actions, and flows."""
    if not isinstance(data, str):
        return None
    patterns = (
        r"menu:(?:add|list|search|edit|delete|summary|low|home|help)",
        r"browse:(?:list|edit|delete|search|low):\d+",
        r"item:(?:view|edit|delete|stock):P\d{3,}:(?:list|edit|delete|search|low):\d+",
        r"search:again",
        r"add:(?:save|cancel|preview|edit):[A-Za-z0-9_-]+",
        r"addfield:(?:name|category|quantity|price):[A-Za-z0-9_-]+",
        r"addcat:(?:Electronics|Clothing|Food & Drinks|Stationery|Accessories|Household|Other|custom):[A-Za-z0-9_-]+",
        r"editfield:(?:name|category|quantity|price):[A-Za-z0-9_-]+",
        r"editcat:(?:Electronics|Clothing|Food & Drinks|Stationery|Accessories|Household|Other|custom):[A-Za-z0-9_-]+",
        r"editconfirm:(?:save|cancel):[A-Za-z0-9_-]+",
        r"delete:(?:yes|no):P\d{3,}:[A-Za-z0-9_-]+",
        r"flow:cancel",
    )
    return data if any(re.fullmatch(pattern, data) for pattern in patterns) else None


def product_line(product):
    return (
        f"{product.id} • {product.name}\n"
        f"  {product.category} | Qty: {product.quantity} | ${product.price} each"
    )


def product_page(products, page=0, page_size=PAGE_SIZE):
    """Return a readable page, 0-based page number, and number of pages."""
    if page_size < 1:
        raise ValueError("page_size must be positive")
    total_pages = max(1, (len(products) + page_size - 1) // page_size)
    page = min(max(page, 0), total_pages - 1)
    selected = products[page * page_size:(page + 1) * page_size]
    text = (
        "📋 Inventory (page " + str(page + 1) + "/" + str(total_pages) + ")\n\n" +
        ("\n\n".join(product_line(item) for item in selected) if selected else "No products found.")
    )
    return text, page, total_pages


def summary_text(summary):
    categories = summary.get("category_breakdown", {})
    ordered = sorted(categories.items(), key=lambda pair: pair[0].casefold())
    category_lines = [
        f"• {name}: {values['products']} product(s), {values['units']} units, ${values['inventory_value']}"
        for name, values in ordered[:15]
    ]
    if len(ordered) > 15:
        category_lines.append(f"• …and {len(ordered)-15} more categories")
    category_summary = "\n".join(category_lines) if category_lines else "No categories yet."
    return (
        "📊 Inventory summary\n\n"
        f"Different products: {summary['total_products']}\n"
        f"Total units: {summary['total_units']}\n"
        f"Low-stock products: {summary['low_stock_count']} "
        f"(quantity ≤ {summary['low_stock_limit']})\n"
        f"Out-of-stock products: {summary.get('out_of_stock_count', 0)}\n"
        f"Total stock value: ${summary['inventory_value']}\n\n"
        f"By category:\n{category_summary}"
    )

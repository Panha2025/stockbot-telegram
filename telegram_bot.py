"""Telegram user interface for the shared COSC 221 inventory manager."""

import logging
from pathlib import Path
import re
import secrets
import time
import warnings
from collections import deque

from bot_helpers import (
    is_authorized_user,
    load_env_file,
    parse_allowed_ids,
    parse_callback_action,
    product_page,
    resolve_config_value,
    summary_text,
)
from inventory import InventoryError, InventoryManager, Product
from storage import DataFileError, InventoryStorage
from postgres_storage import PostgresInventoryManager

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ConversationHandler,
        MessageHandler,
        ApplicationHandlerStop,
        TypeHandler,
        filters,
    )
    from telegram.warnings import PTBUserWarning
    from telegram.error import Conflict, InvalidToken, NetworkError, TelegramError
except ImportError as exc:
    raise SystemExit(
        "Telegram library not installed. Run: .venv/bin/python -m pip install -r requirements.txt"
    ) from exc


BASE = Path(__file__).resolve().parent
DEFAULT_DATA = BASE / "data" / "inventory.json"
EXPECTED_BOT_USERNAME = "SmallShopInventory221Bot"
PAGE_SIZE = 5
LOG = logging.getLogger(__name__)

(
    ADD_NAME, ADD_CATEGORY, ADD_CUSTOM_CATEGORY, ADD_QUANTITY, ADD_PRICE,
    ADD_CONFIRM, ADD_EDIT_FIELD, ADD_EDIT_VALUE,
    SEARCH_QUERY,
    EDIT_FIELD, EDIT_CATEGORY, EDIT_CUSTOM_CATEGORY, EDIT_VALUE, EDIT_CONFIRM,
    DELETE_ID, DELETE_CONFIRM,
) = range(16)

CATEGORIES = (
    "Electronics", "Clothing", "Food & Drinks", "Stationery",
    "Accessories", "Household", "Other",
)
ADD_KEYS = ("add_draft", "add_edit_field")
EDIT_KEYS = ("edit_id", "edit_field", "edit_nonce", "edit_return")
DELETE_KEYS = ("delete_id", "delete_nonce", "delete_return")
ACCOUNT_DELETE_KEY = "delete_account_nonce"
RATE_LIMIT_PER_MINUTE = 60


class ExistingWebhookError(RuntimeError):
    """Polling would remove a pre-existing webhook; require owner action first."""


class BotIdentityError(RuntimeError):
    """The configured token belongs to a different Telegram bot."""


def button(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def main_keyboard():
    return InlineKeyboardMarkup([
        [button("📦 View Inventory", "menu:list"), button("➕ Add Product", "menu:add")],
        [button("🔍 Search Products", "menu:search"), button("✏️ Update Product", "menu:edit")],
        [button("🗑️ Delete Product", "menu:delete"), button("📊 Inventory Summary", "menu:summary")],
        [button("⚠️ Low Stock Alerts", "menu:low")],
        [button("❓ Help", "menu:help")],
    ])


def back_menu_keyboard(back_data="menu:home", back_label="🏠 Main Menu"):
    return InlineKeyboardMarkup([[button(back_label, back_data), button("🏠 Main Menu", "menu:home")]])


def cancel_keyboard():
    return InlineKeyboardMarkup([[button("❌ Cancel", "flow:cancel")]])


def category_keyboard(prefix, nonce):
    rows = [[button(category, f"{prefix}:{category}:{nonce}")] for category in CATEGORIES]
    rows.append([button("✍️ Enter a custom category", f"{prefix}:custom:{nonce}")])
    rows.append([button("❌ Cancel", "flow:cancel")])
    return InlineKeyboardMarkup(rows)


def manager(context):
    store = context.application.bot_data["manager"]
    if hasattr(store, "for_user"):
        # PTB binds this private context field from Update.effective_user.id.
        # It is never read from message text or callback data.
        user_id = getattr(context, "_user_id", getattr(context, "user_id", None))
        if user_id is None:
            raise RuntimeError("Telegram account identity is unavailable")
        return store.for_user(user_id)
    return store


async def reply(update, message, markup=None):
    """Send a new response and acknowledge callbacks exactly once."""
    query = update.callback_query
    if query:
        await query.answer()
        destination = query.message
    else:
        destination = update.effective_message
    await destination.reply_text(message, reply_markup=markup)


async def acknowledge(update, text=None):
    if update.callback_query:
        await update.callback_query.answer(text=text or "")


async def authorized(update, context):
    user = update.effective_user
    chat = update.effective_chat
    access_mode = context.application.bot_data.get("access_mode", "restricted")
    allowed = context.application.bot_data.get("allowed_ids", set())
    if chat is None or chat.type != "private" or user is None:
        LOG.warning("Inventory access denied for a non-private or unidentified update")
        await reply(update, "Please use this bot in a private chat.")
        return False
    permitted = chat.type == "private" and user is not None and (
        access_mode == "public" or is_authorized_user(user.id, chat.type, allowed)
    )
    if not permitted:
        LOG.warning("Inventory access denied; allowlist has no matching user")
        await reply(
            update,
            "🔒 Access denied. Inventory access is locked for this account. Send /myid for account support.\n"
            "No inventory information was shown or changed.",
        )
        return False
    return True


def _within_rate_limit(update, context, user_id):
    """Apply an in-process per-account limit once per Telegram update."""
    update_id = getattr(update, "update_id", None)
    if update_id is not None and context.user_data.get("_rate_limited_update") == update_id:
        return True
    windows = context.application.bot_data.setdefault("request_windows", {})
    now = time.monotonic()
    if user_id not in windows and len(windows) >= 10000:
        for old_id, old_events in list(windows.items()):
            while old_events and now - old_events[0] >= 60:
                old_events.popleft()
            if not old_events:
                windows.pop(old_id, None)
            if len(windows) < 10000:
                break
        if len(windows) >= 10000:
            return False
    events = windows.setdefault(user_id, deque())
    while events and now - events[0] >= 60:
        events.popleft()
    if len(events) >= RATE_LIMIT_PER_MINUTE:
        return False
    events.append(now)
    if update_id is not None:
        context.user_data["_rate_limited_update"] = update_id
    return True


async def rate_limit_update(update, context):
    """Limit every incoming private-chat update, including form text steps."""
    user = update.effective_user
    if user is None or not update.effective_chat or update.effective_chat.type != "private":
        return
    store = context.application.bot_data.get("manager")
    scoped = store.for_user(user.id) if hasattr(store, "for_user") else None
    if scoped is not None and hasattr(scoped, "consume_rate_limit"):
        try:
            within_limit = scoped.consume_rate_limit()
        except Exception as exc:
            LOG.error("Persistent rate-limit check failed (%s)", type(exc).__name__)
            await update.effective_message.reply_text("StockBot is temporarily unavailable. Please retry shortly.")
            raise ApplicationHandlerStop
    else:
        within_limit = _within_rate_limit(update, context, user.id)
    if within_limit:
        return
    query = update.callback_query
    if query:
        await query.answer("Too many requests. Please wait a minute.")
    elif update.effective_message:
        await update.effective_message.reply_text("You’re making requests too quickly. Please wait a minute and try again.")
    raise ApplicationHandlerStop


async def whoami(update, context):
    chat = update.effective_chat
    if chat and chat.type == "private" and update.effective_user:
        await reply(update, f"Your Telegram user ID is: {update.effective_user.id}")
    else:
        await reply(update, "Send /myid in a private chat with the bot.")


async def delete_account_start(update, context):
    if not await authorized(update, context):
        return
    nonce = secrets.token_urlsafe(7)
    context.user_data[ACCOUNT_DELETE_KEY] = nonce
    await reply(
        update,
        "⚠️ PERMANENT ACCOUNT DELETION\n\n"
        "This permanently deletes every product in your cloud inventory. "
        "This cannot be undone. Confirm only if you want to erase your account data.",
        InlineKeyboardMarkup([
            [button("🗑️ Permanently Delete My Account", f"account:delete:{nonce}")],
            [button("Cancel", f"account:cancel:{nonce}")],
        ]),
    )


async def delete_account_callback(update, context):
    if not await authorized(update, context):
        return
    match = re.fullmatch(r"account:(delete|cancel):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    if not match or match.group(2) != context.user_data.get(ACCOUNT_DELETE_KEY):
        await stale_callback(update, context)
        return
    context.user_data.pop(ACCOUNT_DELETE_KEY, None)
    if match.group(1) == "cancel":
        await reply(update, "Account deletion cancelled. Your inventory is unchanged.", main_keyboard())
        return
    try:
        deleted = manager(context).delete_account()
    except Exception as exc:
        LOG.error("Account deletion failed (%s)", type(exc).__name__)
        await reply(update, "Account deletion could not be completed. Please retry later.")
        return
    await reply(
        update,
        "Your account and all associated inventory records have been permanently deleted."
        if deleted else "No account data was found to delete.",
    )


async def admin_status(update, context):
    user = update.effective_user
    chat = update.effective_chat
    admins = context.application.bot_data.get("admin_ids", set())
    if not user or not chat or chat.type != "private" or user.id not in admins:
        await reply(update, "This maintenance command is restricted to configured administrators.")
        return
    store = context.application.bot_data["manager"]
    try:
        healthy = store.check_connection() if hasattr(store, "check_connection") else True
    except Exception as exc:
        LOG.error("Admin health check failed (%s)", type(exc).__name__)
        healthy = False
    await reply(update, "StockBot database: healthy." if healthy else "StockBot database: unavailable.")


async def home(update, context):
    if not await authorized(update, context):
        return
    if context.application.bot_data.get("access_mode") == "public":
        try:
            manager(context).ensure_account()
        except Exception as exc:
            LOG.error("Account initialization failed (%s)", type(exc).__name__)
            await reply(update, "The inventory service is temporarily unavailable. Please try again shortly.")
            return
    summary = manager(context).summary()
    text = (
        "📦 SMALL SHOP INVENTORY\n\n"
        "Welcome to your private inventory manager!\n\n"
        "📊 Inventory Overview\n"
        f"• Total Products: {summary['total_products']}\n"
        f"• Units in Stock: {summary['total_units']}\n"
        f"• Inventory Value: ${summary['inventory_value']}\n"
        f"• Low-Stock Products: {summary['low_stock_count']}\n\n"
        "Choose an action below. Your inventory is private to your Telegram account."
    )
    await reply(update, text, main_keyboard())


async def help_command(update, context):
    if not await authorized(update, context):
        return
    threshold = manager(context).low_stock_limit
    await reply(
        update,
        "❓ INVENTORY BOT HELP\n\n"
        "Use the buttons to browse, add, search, update, or delete products.\n"
        "• Add: enter product details, review the preview, then save.\n"
        "• Update: select a product and field; confirm the preview to apply it.\n"
        "• Delete: select a product and confirm before it is removed.\n"
        f"• Low stock: shows items at or below {threshold} units.\n\n"
        "/start — dashboard   /myid — your Telegram ID\n"
        "/add — add product   /list — browse inventory\n"
        "/search — find products   /update or /edit — edit product\n"
        "/delete — delete safely   /summary — inventory report\n"
        "/cancel — cancel an unfinished operation\n"
        "/deleteaccount — permanently erase your cloud inventory (confirmation required)",
        main_keyboard(),
    )


def product_card(product):
    return (
        f"📦 {product.id} — {product.name}\n"
        f"🏷️ {product.category}\n"
        f"📊 Stock: {product.quantity} units\n"
        f"💵 Price: ${product.price:.2f}\n"
        f"💰 Total Value: ${product.stock_value:.2f}"
    )


def product_picker_keyboard(products, mode, page, pages):
    rows = []
    for product in products:
        if mode == "delete":
            rows.append([button(f"🗑️ Delete {product.id}", f"item:delete:{product.id}:{mode}:{page}")])
        elif mode == "edit":
            rows.append([button(f"✏️ Edit {product.id}", f"item:edit:{product.id}:{mode}:{page}")])
        elif mode == "low":
            rows.append([button(f"📦 Update stock · {product.id}", f"item:stock:{product.id}:low:{page}")])
        else:
            rows.append([
                button(f"🔎 {product.id}", f"item:view:{product.id}:{mode}:{page}"),
                button("✏️ Edit", f"item:edit:{product.id}:{mode}:{page}"),
                button("🗑️ Delete", f"item:delete:{product.id}:{mode}:{page}"),
            ])
    nav = []
    if page > 0:
        nav.append(button("◀ Previous", f"browse:{mode}:{page-1}"))
    if page + 1 < pages:
        nav.append(button("Next ▶", f"browse:{mode}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([button("🏠 Main Menu", "menu:home")])
    return InlineKeyboardMarkup(rows)


async def show_products(update, context, page=0, mode="list", products=None, title=None):
    if not await authorized(update, context):
        return
    all_products = manager(context).list_products() if products is None else list(products)
    if mode == "low":
        all_products.sort(key=lambda product: (product.quantity, int(product.id[1:])))
    else:
        all_products.sort(key=lambda product: int(product.id[1:]))
    _, page, pages = product_page(all_products, page, PAGE_SIZE)
    selected = all_products[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    if not selected:
        text = title or "📦 INVENTORY"
        text += "\n\nYour inventory is empty. Add your first product to get started."
        await reply(update, text, InlineKeyboardMarkup([
            [button("➕ Add Product", "menu:add")], [button("🏠 Main Menu", "menu:home")]
        ]))
        return
    heading = title or "📦 INVENTORY"
    text = f"{heading}\n\nPage {page+1} of {pages}\n\n" + "\n\n".join(product_card(item) for item in selected)
    if mode == "edit":
        text = f"✏️ CHOOSE A PRODUCT TO UPDATE\n\nPage {page+1} of {pages}\n\n" + "\n\n".join(product_card(item) for item in selected)
    elif mode == "delete":
        text = f"🗑️ CHOOSE A PRODUCT TO DELETE\n\nPage {page+1} of {pages}\n\n" + "\n\n".join(product_card(item) for item in selected)
    elif mode == "low":
        text = f"⚠️ LOW STOCK ALERTS\n\nPage {page+1} of {pages}\n\n" + "\n\n".join(product_card(item) for item in selected)
    elif mode == "search":
        text = f"{title or '🔍 SEARCH RESULTS'}\n\nPage {page+1} of {pages}\n\n" + "\n\n".join(product_card(item) for item in selected)
    await reply(update, text, product_picker_keyboard(selected, mode, page, pages))


async def list_cmd(update, context):
    await show_products(update, context, title="📦 INVENTORY")


async def show_summary(update, context):
    if await authorized(update, context):
        await reply(update, summary_text(manager(context).summary()), main_keyboard())


async def show_low(update, context, page=0):
    if not await authorized(update, context):
        return
    stock = manager(context)
    threshold = stock.low_stock_limit
    products = [item for item in stock.list_products() if item.quantity <= threshold]
    products.sort(key=lambda item: (item.quantity, item.id))
    if not products:
        await reply(update, f"✅ No products are at or below the {threshold}-unit low-stock threshold.", main_keyboard())
        return
    await show_products(update, context, page, mode="low", products=products)


async def show_product_detail(update, context, product_id, mode="list", page=0):
    try:
        product = manager(context).get(product_id)
    except InventoryError as exc:
        await reply(update, f"That product is no longer available. {exc}", back_menu_keyboard())
        return
    rows = [
        [button("✏️ Edit", f"item:edit:{product.id}:{mode}:{page}"),
         button("🗑️ Delete", f"item:delete:{product.id}:{mode}:{page}")],
    ]
    if mode == "low":
        rows[0] = [button("📦 Update Stock", f"item:stock:{product.id}:low:{page}")]
    if mode == "search":
        rows.append([button("🔄 Search Again", "search:again")])
    rows.append([button("↩️ Back", f"browse:{mode}:{page}"), button("🏠 Main Menu", "menu:home")])
    await reply(update, "📦 PRODUCT DETAILS\n\n" + product_card(product), InlineKeyboardMarkup(rows))


async def show_product_page_callback(update, context):
    if not await authorized(update, context):
        return
    match = re.fullmatch(r"browse:(list|edit|delete|search|low):(\d+)", update.callback_query.data or "")
    if not match:
        await stale_callback(update, context)
        return
    mode, page_text = match.groups()
    page = int(page_text)
    if mode == "search":
        query = context.user_data.get("search_query")
        if not query:
            await reply(update, "That search has expired. Please search again.", main_keyboard())
            return
        await search_display(update, context, query, page)
    elif mode == "low":
        await show_low(update, context, page)
    else:
        title = {"list": "📦 INVENTORY", "edit": None, "delete": None}[mode]
        await show_products(update, context, page, mode=mode, title=title)


def _draft_product(draft):
    return Product.create("P001", draft["name"], draft["category"], draft["quantity"], draft["price"])


def add_preview_text(draft):
    product = _draft_product(draft)
    return (
        "📦 PRODUCT PREVIEW\n\n"
        f"Product: {product.name}\n\n"
        f"Category: {product.category}\n\n"
        f"Quantity: {product.quantity}\n\n"
        f"Unit Price: ${product.price:.2f}\n\n"
        f"Total Stock Value: ${product.stock_value:.2f}\n\n"
        "ID: Automatically generated after saving"
    )


def add_confirm_keyboard(nonce):
    return InlineKeyboardMarkup([
        [button("✅ Save Product", f"add:save:{nonce}")],
        [button("✏️ Edit Details", f"add:edit:{nonce}")],
        [button("❌ Cancel", f"add:cancel:{nonce}")],
    ])


async def add_start(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview", "search_query"))
    context.user_data["add_draft"] = {"nonce": secrets.token_urlsafe(5)}
    await reply(update, "➕ ADD PRODUCT · Step 1 of 4\n\n📦 What is your product's name?", cancel_keyboard())
    return ADD_NAME


async def add_name(update, context):
    try:
        Product.create("P001", update.message.text, "Other", 0, "0")
    except InventoryError as exc:
        await reply(update, f"{exc}\n\nPlease enter a valid product name:")
        return ADD_NAME
    context.user_data["add_draft"]["name"] = update.message.text.strip()
    nonce = context.user_data["add_draft"]["nonce"]
    await reply(update, "➕ ADD PRODUCT · Step 2 of 4\n\n🏷️ Choose a category or enter your own:", category_keyboard("addcat", nonce))
    return ADD_CATEGORY


async def add_category_choice(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    match = re.fullmatch(r"addcat:(.+):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    draft = context.user_data.get("add_draft", {})
    if not match or match.group(2) != draft.get("nonce"):
        await reply(update, "This category selection expired. Start adding the product again.", main_keyboard())
        return ConversationHandler.END
    selected = match.group(1)
    if selected == "custom":
        await reply(update, "Type a category name (up to 40 characters):", cancel_keyboard())
        return ADD_CUSTOM_CATEGORY
    if selected not in CATEGORIES:
        await stale_callback(update, context)
        return ADD_CATEGORY
    draft["category"] = selected
    await reply(update, "➕ ADD PRODUCT · Step 3 of 4\n\n📦 How many units do you have?", cancel_keyboard())
    return ADD_QUANTITY


async def add_custom_category(update, context):
    try:
        Product.create("P001", "Item", update.message.text, 0, "0")
    except InventoryError as exc:
        await reply(update, f"{exc}\n\nEnter a valid category:", cancel_keyboard())
        return ADD_CUSTOM_CATEGORY
    context.user_data["add_draft"]["category"] = update.message.text.strip()
    await reply(update, "➕ ADD PRODUCT · Step 3 of 4\n\n📦 How many units do you have?", cancel_keyboard())
    return ADD_QUANTITY


async def add_quantity(update, context):
    try:
        validated = Product.create("P001", "Item", "Other", update.message.text, "0")
    except InventoryError as exc:
        await reply(update, f"{exc}\n\nEnter a whole number from 0 to 1,000,000:", cancel_keyboard())
        return ADD_QUANTITY
    context.user_data["add_draft"]["quantity"] = validated.quantity
    await reply(update, "➕ ADD PRODUCT · Step 4 of 4\n\n💰 What is the price per unit? (for example 0.50)", cancel_keyboard())
    return ADD_PRICE


async def add_price(update, context):
    draft = context.user_data.get("add_draft")
    if not draft:
        await reply(update, "This add-product session expired. Start again with /add.", main_keyboard())
        return ConversationHandler.END
    try:
        _draft_product({**draft, "price": update.message.text})
    except (InventoryError, KeyError) as exc:
        await reply(update, f"{exc}\n\nEnter a non-negative price with up to 2 decimal places:", cancel_keyboard())
        return ADD_PRICE
    draft["price"] = update.message.text.strip()
    await reply(update, add_preview_text(draft), add_confirm_keyboard(draft["nonce"]))
    return ADD_CONFIRM


async def add_edit_field(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    match = re.fullmatch(r"add:edit:([A-Za-z0-9_-]+)", update.callback_query.data or "")
    draft = context.user_data.get("add_draft", {})
    if not match or match.group(1) != draft.get("nonce"):
        await stale_callback(update, context)
        return ConversationHandler.END
    nonce = draft["nonce"]
    await reply(update, "Which detail would you like to edit?", InlineKeyboardMarkup([
        [button("Product Name", f"addfield:name:{nonce}"), button("Category", f"addfield:category:{nonce}")],
        [button("Quantity", f"addfield:quantity:{nonce}"), button("Price", f"addfield:price:{nonce}")],
        [button("↩️ Back to Preview", f"add:preview:{nonce}")],
    ]))
    return ADD_EDIT_FIELD


async def add_preview_start(update, context):
    match = re.fullmatch(r"add:preview:([A-Za-z0-9_-]+)", update.callback_query.data or "")
    draft = context.user_data.get("add_draft", {})
    if not match or match.group(1) != draft.get("nonce"):
        await stale_callback(update, context)
        return ConversationHandler.END
    await reply(update, add_preview_text(draft), add_confirm_keyboard(draft["nonce"]))
    return ADD_CONFIRM


async def add_edit_value_start(update, context):
    match = re.fullmatch(r"addfield:(name|category|quantity|price):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    draft = context.user_data.get("add_draft", {})
    if not match or match.group(2) != draft.get("nonce"):
        await stale_callback(update, context)
        return ConversationHandler.END
    field = match.group(1)
    context.user_data["add_edit_field"] = field
    if field == "category":
        prompt = "Type the new category name (up to 40 characters):"
    else:
        labels = {"name": "product name", "quantity": "quantity", "price": "unit price"}
        prompt = f"Enter the new {labels[field]} (current: {draft.get(field)}):"
    await reply(update, prompt, cancel_keyboard())
    return ADD_EDIT_VALUE


async def add_edit_value(update, context):
    field = context.user_data.get("add_edit_field")
    draft = context.user_data.get("add_draft")
    if not draft or field not in ("name", "category", "quantity", "price"):
        await reply(update, "This preview edit expired. Start again with /add.", main_keyboard())
        return ConversationHandler.END
    candidate = update.message.text
    values = {**draft, field: candidate}
    try:
        product = _draft_product(values)
    except InventoryError as exc:
        await reply(update, f"{exc}\n\nPlease enter a valid {field}:", cancel_keyboard())
        return ADD_EDIT_VALUE
    draft[field] = product.quantity if field == "quantity" else str(product.price) if field == "price" else getattr(product, field)
    context.user_data.pop("add_edit_field", None)
    await reply(update, add_preview_text(draft), add_confirm_keyboard(draft["nonce"]))
    return ADD_CONFIRM


async def add_confirmation(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    match = re.fullmatch(r"add:(save|cancel|preview):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    draft = context.user_data.get("add_draft")
    if not match or not draft or match.group(2) != draft.get("nonce"):
        await stale_callback(update, context)
        return ConversationHandler.END
    action = match.group(1)
    if action == "preview":
        await reply(update, add_preview_text(draft), add_confirm_keyboard(draft["nonce"]))
        return ADD_CONFIRM
    if action == "cancel":
        context.user_data.pop("add_draft", None)
        await reply(update, "❌ Product not added. No inventory data changed.", main_keyboard())
        return ConversationHandler.END
    try:
        product = manager(context).add(
            name=draft["name"], category=draft["category"],
            quantity=draft["quantity"], price=draft["price"],
            idempotency_key=draft["nonce"],
        )
    except (InventoryError, DataFileError) as exc:
        await reply(update, f"Could not save the product: {exc}\nYour preview is still here; you can retry or cancel.", add_confirm_keyboard(draft["nonce"]))
        return ADD_CONFIRM
    context.user_data.pop("add_draft", None)
    context.user_data.pop("add_edit_field", None)
    await reply(update, f"✅ Product saved successfully\n\n{product_card(product)}", InlineKeyboardMarkup([
        [button("➕ Add Another", "menu:add")],
        [button("📦 View Inventory", "menu:list")],
        [button("🏠 Main Menu", "menu:home")],
    ]))
    return ConversationHandler.END


def command_arg(update):
    message = update.message
    return message.text.partition(" ")[2].strip() if message and message.text else ""


async def search_start(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview", "search_query"))
    query = command_arg(update)
    if query:
        await search_display(update, context, query)
        return ConversationHandler.END
    await reply(update, "🔍 What product are you looking for?\nSearch by name, ID, or category.", cancel_keyboard())
    return SEARCH_QUERY


async def search_input(update, context):
    query = update.message.text.strip()
    if not query:
        await reply(update, "Please enter a keyword, product ID, or category:", cancel_keyboard())
        return SEARCH_QUERY
    await search_display(update, context, query)
    return ConversationHandler.END


async def search_display(update, context, query, page=0):
    if not await authorized(update, context):
        return
    products = manager(context).search(query)
    context.user_data["search_query"] = query
    if not products:
        context.user_data.pop("search_query", None)
        await reply(update, "No products found. Try another keyword.", InlineKeyboardMarkup([
            [button("🔄 Search Again", "search:again")], [button("🏠 Main Menu", "menu:home")]
        ]))
        return
    await show_products(update, context, page, mode="search", products=products,
                        title=f"🔍 RESULTS FOR: {query[:60]}")


async def edit_start(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview",))
    product_id = command_arg(update).strip().upper()
    if product_id:
        return await select_edit_product(update, context, product_id, "list", 0)
    await show_products(update, context, mode="edit")
    return ConversationHandler.END


async def select_edit_product(update, context, product_id, return_mode="list", page=0):
    if not await authorized(update, context):
        return ConversationHandler.END
    try:
        product = manager(context).get(product_id)
    except InventoryError as exc:
        await reply(update, f"{exc}\nChoose a product from the list or try another ID.", main_keyboard())
        return ConversationHandler.END
    nonce = secrets.token_urlsafe(5)
    context.user_data.update(edit_id=product.id, edit_nonce=nonce, edit_return=(return_mode, page))
    await reply(update, f"✏️ EDIT PRODUCT\n\n📦 {product.name} ({product.id})\n\nWhat would you like to change?", InlineKeyboardMarkup([
        [button("Product Name", f"editfield:name:{nonce}"), button("Category", f"editfield:category:{nonce}")],
        [button("Quantity", f"editfield:quantity:{nonce}"), button("Price", f"editfield:price:{nonce}")],
        [button("↩️ Back", f"browse:{return_mode}:{page}"), button("🏠 Main Menu", "menu:home")],
    ]))
    return EDIT_FIELD


async def item_edit_entry(update, context):
    match = re.fullmatch(r"item:edit:(P\d{3,}):(list|edit|delete|search|low):(\d+)", update.callback_query.data or "")
    if not match:
        await stale_callback(update, context)
        return ConversationHandler.END
    product_id, mode, page = match.groups()
    return await select_edit_product(update, context, product_id, mode, int(page))


async def edit_field(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    match = re.fullmatch(r"editfield:(name|category|quantity|price):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    product_id = context.user_data.get("edit_id")
    if not match or match.group(2) != context.user_data.get("edit_nonce") or not product_id:
        await stale_callback(update, context)
        return ConversationHandler.END
    field = match.group(1)
    context.user_data["edit_field"] = field
    product = manager(context).get(product_id)
    if field == "category":
        await reply(update, f"🏷️ Current category: {product.category}\nChoose a new category or enter a custom one:", category_keyboard("editcat", match.group(2)))
        return EDIT_CATEGORY
    labels = {"name": "product name", "quantity": "quantity", "price": "unit price"}
    await reply(update, f"Current {labels[field]}: {getattr(product, field)}\nSend the new value.", cancel_keyboard())
    return EDIT_VALUE


async def edit_category_choice(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    match = re.fullmatch(r"editcat:(.+):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    if not match or match.group(2) != context.user_data.get("edit_nonce"):
        await stale_callback(update, context)
        return ConversationHandler.END
    if match.group(1) == "custom":
        await reply(update, "Type the new category name (up to 40 characters):", cancel_keyboard())
        return EDIT_CUSTOM_CATEGORY
    if match.group(1) not in CATEGORIES:
        await stale_callback(update, context)
        return EDIT_CATEGORY
    return await prepare_edit_preview(update, context, "category", match.group(1))


async def edit_custom_category(update, context):
    return await prepare_edit_preview(update, context, "category", update.message.text)


async def edit_value(update, context):
    return await prepare_edit_preview(update, context, context.user_data.get("edit_field"), update.message.text)


async def prepare_edit_preview(update, context, field, value):
    product_id = context.user_data.get("edit_id")
    if not product_id or field not in ("name", "category", "quantity", "price"):
        await reply(update, "This edit session expired. Choose the product again.", main_keyboard())
        return ConversationHandler.END
    original = manager(context).get(product_id)
    try:
        preview = Product.create(
            original.id,
            value if field == "name" else original.name,
            value if field == "category" else original.category,
            value if field == "quantity" else original.quantity,
            value if field == "price" else original.price,
        )
    except InventoryError as exc:
        await reply(update, f"{exc}\nPlease enter a valid {field}:", cancel_keyboard())
        return EDIT_CUSTOM_CATEGORY if field == "category" else EDIT_VALUE
    context.user_data["edit_preview"] = (field, getattr(preview, field))
    text = (
        "✏️ CONFIRM PRODUCT UPDATE\n\n"
        f"📦 {preview.name} ({preview.id})\n"
        f"🏷️ Category: {preview.category}\n"
        f"📊 Stock: {preview.quantity} units\n"
        f"💵 Price: ${preview.price:.2f}\n"
        f"💰 Total Value: ${preview.stock_value:.2f}\n\n"
        f"{field.title()}: {getattr(original, field)} → {getattr(preview, field)}"
    )
    nonce = context.user_data["edit_nonce"]
    await reply(update, text, InlineKeyboardMarkup([
        [button("✅ Save Update", f"editconfirm:save:{nonce}")],
        [button("❌ Cancel", f"editconfirm:cancel:{nonce}")],
    ]))
    return EDIT_CONFIRM


async def edit_confirm(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    match = re.fullmatch(r"editconfirm:(save|cancel):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    if not match or match.group(2) != context.user_data.get("edit_nonce"):
        await stale_callback(update, context)
        return ConversationHandler.END
    if match.group(1) == "cancel":
        _clear_user_flow(context, EDIT_KEYS + ("edit_preview",))
        await reply(update, "Update cancelled. No data changed.", main_keyboard())
        return ConversationHandler.END
    product_id = context.user_data.get("edit_id")
    field_value = context.user_data.get("edit_preview")
    if not product_id or not field_value:
        await stale_callback(update, context)
        return ConversationHandler.END
    field, value = field_value
    try:
        product = manager(context).update(product_id, **{field: value})
    except (InventoryError, DataFileError) as exc:
        await reply(update, f"Could not update product: {exc}", main_keyboard())
        return ConversationHandler.END
    _clear_user_flow(context, EDIT_KEYS + ("edit_preview",))
    await reply(update, f"✅ Product updated successfully\n\n{product_card(product)}", InlineKeyboardMarkup([
        [button("📦 View Inventory", "menu:list")], [button("🏠 Main Menu", "menu:home")]
    ]))
    return ConversationHandler.END


async def delete_start(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview",))
    product_id = command_arg(update).strip().upper()
    if not product_id:
        await show_products(update, context, mode="delete")
        return ConversationHandler.END
    return await prepare_delete(update, context, product_id, "list", 0)


async def prepare_delete(update, context, product_id, return_mode="list", page=0):
    if not await authorized(update, context):
        return ConversationHandler.END
    try:
        product = manager(context).get(product_id)
    except InventoryError as exc:
        await reply(update, f"{exc}\nSelect a product from inventory to delete.", main_keyboard())
        return ConversationHandler.END
    nonce = secrets.token_urlsafe(5)
    context.user_data.update(delete_id=product.id, delete_nonce=nonce, delete_return=(return_mode, page))
    await reply(update,
        "🗑️ DELETE PRODUCT\n\n"
        f"Product: {product.name}\nID: {product.id}\nCategory: {product.category}\nQuantity: {product.quantity}\n\n"
        "Are you sure you want to delete this product?",
        InlineKeyboardMarkup([
            [button("🔴 Yes, Delete", f"delete:yes:{product.id}:{nonce}")],
            [button("❌ Cancel", f"delete:no:{product.id}:{nonce}")],
        ]),
    )
    return DELETE_CONFIRM


async def item_delete_entry(update, context):
    match = re.fullmatch(r"item:delete:(P\d{3,}):(list|edit|delete|search|low):(\d+)", update.callback_query.data or "")
    if not match:
        await stale_callback(update, context)
        return ConversationHandler.END
    product_id, mode, page = match.groups()
    return await prepare_delete(update, context, product_id, mode, int(page))


async def delete_confirm(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    match = re.fullmatch(r"delete:(yes|no):([A-Z0-9]+):([A-Za-z0-9_-]+)", update.callback_query.data or "")
    if (not match or match.group(2) != context.user_data.get("delete_id")
            or match.group(3) != context.user_data.get("delete_nonce")):
        await stale_callback(update, context)
        return ConversationHandler.END
    product_id = context.user_data["delete_id"]
    if match.group(1) == "no":
        _clear_user_flow(context, DELETE_KEYS)
        await reply(update, "Deletion cancelled. No data changed.", InlineKeyboardMarkup([
            [button("📦 View Inventory", "menu:list")], [button("🏠 Main Menu", "menu:home")]
        ]))
        return ConversationHandler.END
    try:
        product = manager(context).delete(product_id)
    except (InventoryError, DataFileError) as exc:
        await reply(update, f"Could not delete product: {exc}", main_keyboard())
        return ConversationHandler.END
    _clear_user_flow(context, DELETE_KEYS)
    await reply(update, f"✅ Deleted {product.name} ({product.id}).", InlineKeyboardMarkup([
        [button("📦 View Inventory", "menu:list")], [button("🏠 Main Menu", "menu:home")]
    ]))
    return ConversationHandler.END


async def start_low_stock_edit(update, context):
    if not await authorized(update, context):
        return ConversationHandler.END
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview",))
    match = re.fullmatch(r"item:stock:([A-Z0-9]+):low:(\d+)", update.callback_query.data or "")
    if not match:
        await stale_callback(update, context)
        return ConversationHandler.END
    try:
        product = manager(context).get(match.group(1))
    except InventoryError:
        await reply(update, "That product is no longer available.", main_keyboard())
        return ConversationHandler.END
    nonce = secrets.token_urlsafe(5)
    context.user_data.update(edit_id=product.id, edit_field="quantity", edit_nonce=nonce, edit_return=("low", int(match.group(2))))
    await reply(update, f"Current stock for {product.name} ({product.id}): {product.quantity} units.\nSend the new quantity:", cancel_keyboard())
    return EDIT_VALUE


def _clear_user_flow(context, keys):
    for key in keys:
        context.user_data.pop(key, None)


async def cancel(update, context):
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview", "search_query"))
    await reply(update, "Cancelled. No unfinished changes were saved.", main_keyboard())
    return ConversationHandler.END


async def restart_menu(update, context):
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview",))
    await home(update, context)
    return ConversationHandler.END


async def navigate(update, context):
    if not await authorized(update, context):
        return
    action = update.callback_query.data or ""
    action = parse_callback_action(action)
    if action is None:
        await stale_callback(update, context)
        return
    if action == "menu:home":
        await home(update, context)
    elif action == "menu:list":
        await show_products(update, context, title="📦 INVENTORY")
    elif action.startswith("browse:"):
        await show_product_page_callback(update, context)
    elif action == "menu:summary":
        await show_summary(update, context)
    elif action == "menu:low":
        await show_low(update, context)
    elif action == "menu:help":
        await help_command(update, context)
    elif action.startswith("item:"):
        await product_action(update, context)
    elif action == "search:again":
        await search_start(update, context)
    elif action.startswith("delete:"):
        await stale_callback(update, context)
    elif action.startswith("account:"):
        await delete_account_callback(update, context)
    else:
        await stale_callback(update, context)


async def product_action(update, context):
    if not await authorized(update, context):
        return
    match = re.fullmatch(r"item:(view|edit|delete|stock):(P\d{3,}):(list|edit|delete|search|low):(\d+)", update.callback_query.data or "")
    if not match:
        await stale_callback(update, context)
        return
    action, product_id, mode, page_text = match.groups()
    page = int(page_text)
    if action == "view":
        await show_product_detail(update, context, product_id, mode, page)
    elif action == "edit":
        await stale_callback(update, context)
    elif action == "delete":
        await stale_callback(update, context)
    elif action == "stock" and mode == "low":
        await stale_callback(update, context)


async def stale_callback(update, context):
    if not await authorized(update, context):
        return
    await reply(update, "That button has expired. Please choose an action from the current menu.", main_keyboard())


async def unknown(update, context):
    if not await authorized(update, context):
        return
    await reply(update, "I didn't understand that. Use /start for the menu or /help for instructions.", main_keyboard())


async def error_handler(update, context):
    error = context.error
    context.application.bot_data["_webhook_handler_error"] = True
    LOG.error("Telegram update failed (%s)", type(error).__name__)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("Sorry, that action failed. Your saved inventory is safe. Try /start.")
        except Exception:
            LOG.warning("Could not send Telegram error response")


async def preflight_telegram(application):
    bot_info = await application.bot.get_me()
    if (bot_info.username or "").casefold() != EXPECTED_BOT_USERNAME.casefold():
        raise BotIdentityError(
            f"Configured token belongs to @{bot_info.username or 'unknown'}, not @{EXPECTED_BOT_USERNAME}."
        )
    webhook = await application.bot.get_webhook_info()
    if webhook.url:
        raise ExistingWebhookError(
            "A Telegram webhook is currently configured. Polling would remove it, so the bot stopped safely. "
            "Review it and remove it yourself only if you intend to switch to polling."
        )
    LOG.info("Telegram identity verified as @%s; no webhook is configured", bot_info.username)


async def log_incoming_command(update, context):
    message = update.effective_message
    text_value = message.text if message and message.text else ""
    match = re.match(r"^/([A-Za-z0-9_]+)(?:@[^\s]+)?", text_value)
    if match:
        LOG.info("Received /%s", match.group(1).lower())


def build_application(token, allowed_ids, stock, access_mode="restricted", admin_ids=None, persistence=None):
    if access_mode == "public" and not hasattr(stock, "for_user"):
        raise ValueError("Public mode requires user-scoped PostgreSQL storage")
    builder = Application.builder().token(token).concurrent_updates(False).post_init(preflight_telegram)
    if persistence is not None:
        builder = builder.persistence(persistence)
    application = builder.build()
    application.bot_data["manager"] = stock
    application.bot_data["allowed_ids"] = allowed_ids
    application.bot_data["access_mode"] = access_mode
    application.bot_data["admin_ids"] = set(admin_ids or ())
    text_input = filters.TEXT & ~filters.COMMAND

    entry_points = [
        CommandHandler("add", add_start),
        CommandHandler("search", search_start),
        CommandHandler(["update", "edit"], edit_start),
        CommandHandler("delete", delete_start),
        CallbackQueryHandler(add_start, pattern=r"^menu:add$"),
        CallbackQueryHandler(search_start, pattern=r"^(menu:search|search:again)$"),
        CallbackQueryHandler(edit_start, pattern=r"^menu:edit$"),
        CallbackQueryHandler(delete_start, pattern=r"^menu:delete$"),
        CallbackQueryHandler(start_low_stock_edit, pattern=r"^item:stock:"),
        CallbackQueryHandler(item_edit_entry, pattern=r"^item:edit:"),
        CallbackQueryHandler(item_delete_entry, pattern=r"^item:delete:"),
    ]
    states = {
        ADD_NAME: [MessageHandler(text_input, add_name)],
        ADD_CATEGORY: [CallbackQueryHandler(add_category_choice, pattern=r"^addcat:")],
        ADD_CUSTOM_CATEGORY: [MessageHandler(text_input, add_custom_category)],
        ADD_QUANTITY: [MessageHandler(text_input, add_quantity)],
        ADD_PRICE: [MessageHandler(text_input, add_price)],
        ADD_CONFIRM: [
            CallbackQueryHandler(add_confirmation, pattern=r"^add:(save|cancel|preview):"),
            CallbackQueryHandler(add_edit_field, pattern=r"^add:edit:"),
        ],
        ADD_EDIT_FIELD: [
            CallbackQueryHandler(add_edit_value_start, pattern=r"^addfield:"),
            CallbackQueryHandler(add_preview_start, pattern=r"^add:preview:"),
        ],
        ADD_EDIT_VALUE: [MessageHandler(text_input, add_edit_value)],
        SEARCH_QUERY: [MessageHandler(text_input, search_input)],
        EDIT_FIELD: [CallbackQueryHandler(edit_field, pattern=r"^editfield:")],
        EDIT_CATEGORY: [CallbackQueryHandler(edit_category_choice, pattern=r"^editcat:")],
        EDIT_CUSTOM_CATEGORY: [MessageHandler(text_input, edit_custom_category)],
        EDIT_VALUE: [MessageHandler(text_input, edit_value)],
        EDIT_CONFIRM: [CallbackQueryHandler(edit_confirm, pattern=r"^editconfirm:")],
        DELETE_ID: [MessageHandler(text_input, delete_id_input)],
        DELETE_CONFIRM: [CallbackQueryHandler(delete_confirm, pattern=r"^delete:(yes|no):")],
    }
    # This flow intentionally combines message steps and inline callbacks.
    # per_message=True would detach the text steps from the initiating button.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"If 'per_message=False', 'CallbackQueryHandler' will not be tracked for every message.*",
            category=PTBUserWarning,
        )
        conversation = ConversationHandler(
            entry_points=entry_points,
            states=states,
            fallbacks=[
                CommandHandler("cancel", cancel),
                CommandHandler("start", restart_menu),
                CallbackQueryHandler(restart_menu, pattern=r"^menu:home$"),
                CallbackQueryHandler(cancel, pattern=r"^flow:cancel$"),
                CallbackQueryHandler(exit_flow_to_navigation, pattern=r"^(browse:|menu:(list|summary|low|help))"),
            ],
            allow_reentry=True,
            per_chat=True,
            per_user=True,
            per_message=False,
            persistent=persistence is not None,
            name="stockbot_user_conversation" if persistence is not None else None,
        )
    application.add_handler(TypeHandler(Update, log_incoming_command), group=-1)
    application.add_handler(TypeHandler(Update, rate_limit_update), group=-2)
    application.add_handler(CommandHandler("myid", whoami))
    application.add_handler(CommandHandler("deleteaccount", delete_account_start))
    application.add_handler(CallbackQueryHandler(delete_account_callback, pattern=r"^account:"))
    application.add_handler(CommandHandler("status", admin_status))
    application.add_handler(conversation)
    application.add_handler(CommandHandler("start", home))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_cmd))
    application.add_handler(CommandHandler("summary", show_summary))
    application.add_handler(CommandHandler("low", show_low))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(navigate, pattern=r"^(menu:|browse:|item:|search:again|delete:|account:|add:|addcat:|addfield:|editfield:|editcat:|editconfirm:|flow:cancel)"))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    application.add_handler(MessageHandler(text_input, unknown))
    application.add_error_handler(error_handler)
    return application


async def delete_id_input(update, context):
    return await prepare_delete(update, context, update.message.text.strip().upper())


async def exit_flow_to_navigation(update, context):
    _clear_user_flow(context, ADD_KEYS + EDIT_KEYS + DELETE_KEYS + ("edit_preview", "search_query"))
    await navigate(update, context)
    return ConversationHandler.END


async def main_menu_callback(update, context):
    await navigate(update, context)


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    LOG.setLevel(logging.INFO)
    config = load_env_file(BASE / ".env")
    token, _ = resolve_config_value("TELEGRAM_BOT_TOKEN", config)
    raw_ids, id_source = resolve_config_value(
        "TELEGRAM_ALLOWED_USER_IDS", config, aliases=("TELEGRAM_ALLOWED_IDS",)
    )
    raw_low_stock_limit, low_source = resolve_config_value("LOW_STOCK_LIMIT", config, default="5")
    file_name, path_source = resolve_config_value("INVENTORY_DATA_PATH", config)
    access_mode, access_source = resolve_config_value("BOT_ACCESS_MODE", config, default="restricted")
    backend, backend_source = resolve_config_value("STORAGE_BACKEND", config, default="json")
    database_url, _ = resolve_config_value("DATABASE_URL", config)
    ssl_root_cert, cert_source = resolve_config_value("DATABASE_SSL_ROOT_CERT", config)
    raw_admin_ids, admin_source = resolve_config_value("TELEGRAM_ADMIN_USER_IDS", config)
    if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("Missing TELEGRAM_BOT_TOKEN. Follow README.md to configure .env.")
        return 1
    try:
        if access_mode not in {"public", "restricted"}:
            raise ValueError("BOT_ACCESS_MODE must be public or restricted")
        if backend not in {"json", "postgres"}:
            raise ValueError("STORAGE_BACKEND must be json or postgres")
        if access_mode == "public" and backend != "postgres":
            raise ValueError("Public access requires PostgreSQL storage to keep each user's inventory private")
        allowed_ids = parse_allowed_ids(raw_ids) if access_mode == "restricted" else set()
        admin_ids = parse_allowed_ids(raw_admin_ids)
        low_stock_limit = int(raw_low_stock_limit)
        if low_stock_limit < 0:
            raise ValueError("LOW_STOCK_LIMIT must be zero or greater")
        if backend == "postgres":
            if not database_url:
                raise ValueError("DATABASE_URL is required when STORAGE_BACKEND=postgres")
            if not ssl_root_cert:
                raise ValueError("DATABASE_SSL_ROOT_CERT must point to Supabase's downloaded root certificate")
            cert_path = Path(ssl_root_cert).expanduser()
            if not cert_path.is_absolute():
                cert_path = BASE / cert_path
            if not cert_path.is_file():
                raise ValueError("DATABASE_SSL_ROOT_CERT file was not found")
            stock = PostgresInventoryManager(
                database_url, low_stock_limit=low_stock_limit, ssl_root_cert=cert_path,
            )
            if not stock.check_connection():
                raise ValueError("PostgreSQL health check failed")
        else:
            data_path = Path(file_name).expanduser() if file_name else DEFAULT_DATA
            if not data_path.is_absolute():
                data_path = BASE / data_path
            stock = InventoryManager(InventoryStorage(data_path), low_stock_limit=low_stock_limit)
    except (ValueError, DataFileError) as exc:
        print(f"Cannot start safely: {exc}")
        return 1
    except Exception as exc:
        LOG.error("Storage initialization failed (%s)", type(exc).__name__)
        print("Cannot start safely: storage initialization failed. Check database setup and credentials privately.")
        return 1
    if access_mode == "restricted" and not allowed_ids:
        print("Access locked: TELEGRAM_ALLOWED_USER_IDS is empty. /myid remains available to unlock inventory.")
    LOG.info("Access mode loaded from %s: %s", access_source, access_mode)
    if access_mode == "restricted":
        LOG.info("Loaded allowlist from %s (%d ID(s))", id_source, len(allowed_ids))
    LOG.info("Loaded storage backend from %s: %s", backend_source, backend)
    if backend == "postgres":
        LOG.info("Verified database TLS using root certificate from %s", cert_source)
    LOG.info("Loaded low-stock limit from %s; admin IDs from %s (%d configured)", low_source, admin_source, len(admin_ids))
    if backend == "json":
        LOG.info("Loaded local inventory path from %s", path_source)
    application = build_application(token, allowed_ids, stock, access_mode, admin_ids)
    print("Starting Telegram checks and polling. Press Ctrl+C to stop.")
    try:
        application.run_polling(drop_pending_updates=False, allowed_updates=["message", "callback_query"])
    except InvalidToken:
        print("Invalid TELEGRAM_BOT_TOKEN. Check it privately with BotFather; the token was not logged.")
        return 1
    except ExistingWebhookError as exc:
        print(exc)
        return 1
    except BotIdentityError as exc:
        print(f"Bot identity check failed: {exc}")
        return 1
    except Conflict:
        print("Another process is polling this bot. Stop the duplicate instance and retry.")
        return 1
    except NetworkError:
        print("Could not connect to Telegram. Check the network connection and retry.")
        return 1
    except TelegramError as exc:
        LOG.error("Telegram API failure (%s)", type(exc).__name__)
        print(f"Telegram API error ({type(exc).__name__}); no credential details were shown.")
        return 1
    except KeyboardInterrupt:
        print("Bot stopped cleanly.")
        return 0
    except Exception as exc:
        LOG.error("Unexpected bot failure (%s)", type(exc).__name__)
        print(f"Unexpected bot failure ({type(exc).__name__}); details were withheld.")
        return 1
    LOG.info("Telegram polling stopped")
    print("Bot stopped cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# COSC 221 — Short Project Proposal

**Team number:** [TeamXX from registration sheet]  
**Members:** [Member 1], [Member 2], [Member 3], [Member 4 optional]  
**Topic:** Small Shop Inventory  
**Timeframe:** Four weeks

## Everyday problem

Small shops need a way to keep track of item names, categories, quantities and prices. If records are kept only on paper, checking available stock and calculating inventory value can take time. This project creates a simple Python inventory manager, with an optional Telegram bot for easier access.

## Main record (one type only)

| Field | Example |
|---|---|
| Unique ID | P001 |
| Item name | Rice 5kg |
| Category | Groceries |
| Quantity | 12 |
| Unit price in USD | 13.50 |

## Python terminal menu (required)

```text
1. Add a product
2. View all products
3. Search products
4. Update a product
5. Delete a product
6. Inventory summary
7. Exit
```

## Core features

Add a product with a unique ID and validation; show all items; search by ID/name/category; update by ID; delete only after confirmation; save and load JSON; summarize total products, units, low-stock items, and inventory value.

## Optional extension

A Telegram bot with menu buttons for add, view, search, update, delete, summaries and low-stock warnings. This is **not required** for the core Python assignment, and the class's instructions give no automatic extra marks for interfaces. The team will prioritize Python reliability first.

## Suggested division of work (replace with actual contributions)

- **Member 1:** `inventory.py` — Product class and validation
- **Member 2:** `storage.py`, `data/` — JSON persistence and damage handling
- **Member 3:** `app.py`, tests — menu and input handling
- **Member 4 (if present):** `telegram_bot.py`, `bot_helpers.py` — optional bot

*Replace this suggestion with the actual allocation agreed with the team.*

## Suggested milestones

| Week | Target |
|---|---|
| 1 | Register team, agree topic, record fields, menu and proposal |
| 2 | Working add, view and search in Python terminal |
| 3 | Update, delete, JSON save/load, summaries and error handling |
| 4 | Test, prepare README, live demo and optional Telegram integration |

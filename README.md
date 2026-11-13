# COSC 221 Final Project — Small Shop Inventory + Telegram Bot

**Topic:** Small Shop Inventory (from the professor's list of approved topics)

**Language:** Python 3.10+

**Project type:** Python terminal application with an optional local Telegram bot

**Storage:** Local JSON files; no database, website, or hosting required

**Team:** [Fill in registered team number], [Member 1], [Member 2], [Member 3], [Member 4 if applicable]

## Start here (the required Python application)

1. Download the ZIP, extract it, open the extracted folder in **VS Code**.
2. Open the VS Code terminal (Terminal > New Terminal).
3. Run:

   ```bash
   python3 app.py
   ```

4. Try menu options **1–7** to add, view, search, update, delete, and summarize products.
5. Exit and run it again: completed changes remain in `data/inventory.json`.

**No downloads or `pip install` are required for the terminal application.**
The low-stock threshold defaults to 5; configure another value with `python3 app.py --low-stock-limit 3`.

## Telegram bot setup

Try the bot: [@SmallShopInventory221Bot](https://t.me/SmallShopInventory221Bot).

The Telegram bot runs locally on your MacBook using polling. It only responds while your MacBook is running the bot and connected to the internet. While it is running, anyone can use the bot in a private Telegram chat. Each Telegram account gets a separate JSON file in `data/telegram_users/`; the CLI continues to use only `data/inventory.json`.

Install the bot dependencies locally with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp -n .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` in `.env`. If the token was exposed, revoke it with `@BotFather` and use the replacement. `.env` is ignored by Git. No Telegram user allowlist or database password is needed. Start the bot with:

```bash
.venv/bin/python telegram_bot.py
```

The bot accepts private chats and scopes every command and button action to Telegram's verified sender ID. It preserves product IDs, pagination, add/search/update/delete, summary, low-stock alerts, confirmed `/deleteaccount`, admin-only `/status`, and the 500-product limit. The local rate limit is per user and resets when the bot restarts. `/myid` remains available.

The bot must be running on your MacBook and connected to the internet. Keep only one polling process active for this token. Telegram inventories remain on this MacBook in files excluded from Git. The CLI and bot use different JSON files and can run at the same time.

## What is in the ZIP?

```text
COSC221_Telegram_Inventory_Final/
├── app.py                 # required command-line menu
├── inventory.py           # Product and InventoryManager classes; validation
├── storage.py             # robust local JSON load / atomic save
├── telegram_bot.py        # optional Telegram bot menus and conversations
├── telegram_storage.py    # separate JSON file for each Telegram account
├── bot_helpers.py         # message formatting and configuration helpers
├── requirements.txt       # only used by Telegram
├── .env.example           # safe configuration template (no real token)
├── .gitignore             # excludes secrets and generated files
├── data/
│   ├── inventory.json     # 10 fictional starting products
│   └── sample_inventory.json  # clean demo copy for resetting
├── tests/
│   ├── test_inventory.py
│   ├── test_cli.py
│   ├── test_bot_helpers.py
│   └── test_telegram_bot.py
├── README.md
├── PROJECT_PROPOSAL.md
├── DEMO_GUIDE.md
├── CONTRIBUTIONS.md
└── TESTING.md
```

## Python and the professor's checklist

- **One main record type:** `Product(id, name, category, quantity, price)`.
- **Two meaningful classes:** `Product` validates/stores one item; `InventoryManager` manages a dictionary indexed by ID, and searches/updates/summarizes items. `InventoryStorage` is an extra file-handling class.
- **Three separated concerns:** `app.py` (menu), `inventory.py` (logic), `storage.py` (JSON).
- **Required features:** add (unique ID), view, search, update by ID, delete with confirmation, save/load, and summaries.
- **Validation:** fields required; quantities nonnegative whole numbers; prices nonnegative with up to two decimal places; friendly unknown-ID errors.
- **Safe file handling:** missing file starts with empty inventory; unreadable/damaged file causes a clear error **without overwriting it**; successful changes save immediately using atomic replacement.
- **Why a dictionary?** IDs are unique keys so each product can be found and updated quickly. Searching names/categories uses a simple loop, appropriate to the course scope.

## Running all automated tests

```bash
python3 -m unittest discover -s tests -v
```

Tests use **temporary files**, not the bundled demonstration data. Telegram interactions are mocked, so no token or live message is needed to run the suite. Activate `.venv` first if you want to exercise PTB application construction too. See `TESTING.md` for observed results and the manual Telegram checklist.

## Resetting sample data

To reset the demonstration, first stop the bot and/or CLI, then copy:

```bash
cp data/sample_inventory.json data/inventory.json
```

This **replaces your current changes**. Back up `data/inventory.json` first if needed.

## Important limitations

- Telegram is an **optional extension**, not the core assignment. The professor does not award automatic extra marks for extra interfaces; request instructor approval if necessary.
- The local Telegram bot cannot answer when your MacBook is off, asleep, or offline. There is no cloud hosting or uptime guarantee.
- Local inventory files are designed for one polling process, not multiple bot copies or multiple machines.
- Data fields are for inventory only. Sales tracking, online accounts, machine learning, and paid services are outside this assignment's scope.
- **Testing disclosure:** Python CLI, storage, helpers and code syntax were tested offline. Live Telegram messaging still requires a personal token and connection and must be tested by your team.

## Before Canvas submission

1. Edit the **team number and names** in README and `CONTRIBUTIONS.md`.
2. Fill in **real work completed by each member** and record your team's **manual Telegram checks** in `TESTING.md`.
3. Practice the **5–7 minute live presentation** in `DEMO_GUIDE.md`; every student should explain part of the code.
4. Remove any personal `.env` (it is not included in the provided ZIP anyway).
5. Rename the final ZIP to `COSC221_TeamName_FinalProject.zip`, replacing `TeamName` with your registered team number, e.g. `COSC221_Team01_FinalProject.zip`.
6. Submit **one ZIP per team** on Canvas.

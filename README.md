# COSC 221 Final Project — Small Shop Inventory + Telegram Bot

**Topic:** Small Shop Inventory (from the professor's list of approved topics)  
**Language:** Python 3.10+  
**Project type:** Python terminal application, with **one optional Telegram interface**  
**Storage:** Local JSON file, no database or website required  
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

The university CLI continues to use local JSON and needs no database. The Telegram bot has two separate configurations:

- **Local course/demo mode:** JSON storage and a restricted numeric allowlist. The bot must be running on your computer.
- **Public hosted mode:** PostgreSQL storage and a private inventory per verified Telegram user. Use the Render worker and Supabase steps in [DEPLOYMENT.md](DEPLOYMENT.md).

Install the bot dependencies locally with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Set a fresh `TELEGRAM_BOT_TOKEN` privately in `.env` for local use. If a token has ever been exposed, revoke it through BotFather and use only its replacement. `.env` is ignored by Git. For local restricted mode, set `TELEGRAM_ALLOWED_USER_IDS` to numeric IDs separated by commas, then run `python telegram_bot.py`. `/myid` remains available while access is locked.

The public deployment uses `BOT_ACCESS_MODE=public`, `STORAGE_BACKEND=postgres`, a new bot token, and a least-privilege database URL stored only in Render secrets. It ignores the local JSON file and never uploads the university sample data. Every Telegram action, including callback product IDs, is scoped to Telegram's verified private-chat user ID. See the deployment guide for account setup, migration, recovery, monitoring, and plan costs.

Supported features include `/start`, add, paginated view, search, update, confirmed delete, summary, low-stock alerts, and confirmed `/deleteaccount`. Group chats are rejected. The public service rate limits each user and caps an account at 500 products. Data remains until the user deletes their account or the database operator removes it.

Local JSON is designed for one writer at a time. The Telegram local mode and CLI should not run simultaneously against the same JSON file. The hosted bot uses a separate PostgreSQL database and does not share the CLI's sample data.

## What is in the ZIP?

```text
COSC221_Telegram_Inventory_Final/
├── app.py                 # required command-line menu
├── inventory.py           # Product and InventoryManager classes; validation
├── storage.py             # robust local JSON load / atomic save
├── telegram_bot.py        # optional Telegram bot menus and conversations
├── postgres_storage.py    # owner-scoped PostgreSQL storage for public bot
├── migrations/            # Supabase PostgreSQL schema and RLS
├── render.yaml             # always-on background worker blueprint
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
- Local Telegram mode cannot answer when your laptop/computer is off. Hosted mode depends on Render, Supabase, Telegram, and network availability; it has no contractual uptime guarantee.
- Local JSON is intended for one process at a time, not concurrent app/bot runs or multiple machines.
- Data fields are for inventory only. Sales tracking, sign-in accounts, machine learning, and paid services are outside this assignment's scope.
- **Testing disclosure:** Python CLI, storage, helpers and code syntax were tested offline. Live Telegram messaging still requires a personal token and connection and must be tested by your team.

## Before Canvas submission

1. Edit the **team number and names** in README and `CONTRIBUTIONS.md`.
2. Fill in **real work completed by each member** and record your team's **manual Telegram checks** in `TESTING.md`.
3. Practice the **5–7 minute live presentation** in `DEMO_GUIDE.md`; every student should explain part of the code.
4. Remove any personal `.env` (it is not included in the provided ZIP anyway).
5. Rename the final ZIP to `COSC221_TeamName_FinalProject.zip`, replacing `TeamName` with your registered team number, e.g. `COSC221_Team01_FinalProject.zip`.
6. Submit **one ZIP per team** on Canvas.

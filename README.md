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

## Telegram bot setup (optional interface)

Telegram uses the **same InventoryManager and JSON file** as the terminal application. The Telegram bot cannot work until you create a bot with Telegram and supply its token. It also needs internet access, and `telegram_bot.py` must stay running to respond to messages.

### Step 1 — Create a bot in Telegram

1. In Telegram, open the verified **@BotFather** account.
2. Send `/newbot` and follow its instructions to pick a name and a username ending in `bot`.
3. BotFather gives you a **secret API token**. Don't post it in chats, source code, a screenshot, or Canvas.

### Step 2 — Install the Telegram library (Mac / VS Code)

In VS Code's terminal, **inside this project folder**:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate` instead of `source ...`.

### Step 3 — Configure your token

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Open `.env`, paste your secret after `TELEGRAM_BOT_TOKEN=` and leave `TELEGRAM_ALLOWED_USER_IDS=` empty at first.

Example structure (use a **real token privately**, not this placeholder):

```ini
TELEGRAM_BOT_TOKEN=PASTE_YOUR_BOT_TOKEN_HERE
TELEGRAM_ALLOWED_USER_IDS=
INVENTORY_DATA_PATH=
LOW_STOCK_LIMIT=5
```

**Important:** `.env` is intentionally excluded from the ZIP and Git. Never submit real bot tokens.
If a token was ever exposed, revoke/regenerate it privately through BotFather and replace the value in `.env` before starting the bot. This project does not print token values.

### Step 4 — Find your Telegram ID (safe onboarding)

Run:

```bash
python3 telegram_bot.py
```

The bot starts in **locked mode** when there are no allowed IDs. `/myid` is registered before the inventory conversation handler and does not use inventory authorization. Open `@SmallShopInventory221Bot` and send `/myid` in a private chat. It replies with your numeric Telegram user ID. You cannot see/change any inventory yet.

At startup, the bot makes read-only `getMe` and `getWebhookInfo` checks and confirms that the token belongs to `@SmallShopInventory221Bot`. Non-empty process environment values override `.env`; blank exported values fall back to `.env`. Startup logs show the configuration source and allowlist count without printing IDs. If another webhook is configured, the bot stops without deleting it; review the current setup and remove that webhook yourself only if switching to polling. A second polling process is reported as a conflict. Pending updates are preserved at startup.

Now:

1. Stop the program with **Ctrl+C**.
2. Change `.env` to `TELEGRAM_ALLOWED_USER_IDS=123456789` (replace with your actual ID).
3. If multiple team members should access the inventory, use `123456789,987654321`.
4. Start again: `python3 telegram_bot.py`.
5. Send `/start` in your private Telegram bot chat and tap the buttons.

### Step 5 — Test Telegram buttons and commands

| Command/button | What it does |
|---|---|
| `/start` | Open the menu of buttons |
| `/add` | Enter name, choose or type category, quantity, and price; review and confirm. IDs are generated automatically. |
| `/list` | Browse five detailed product cards per page with View, Edit, and Delete buttons |
| `/search pen` | Search by name, category, or ID; `/search` asks for a keyword. Results can be viewed, edited, or deleted. |
| `/update` or `/edit` | Select a product from the list, choose a field, preview, then confirm |
| `/delete` | Select a product and explicitly confirm or cancel deletion |
| `/summary` | Product count, units, stock value, low/out-of-stock counts, and category breakdown |
| `/low` | Products at or below the configured low-stock threshold, with stock update buttons |
| `/cancel` | Cancel an unfinished form |
| `/myid` | Show your own user ID; allowed even in locked mode |

Set `LOW_STOCK_LIMIT` in `.env` to change the bot's low-stock threshold; it defaults to 5. The CLI accepts `--low-stock-limit N`.

**Access control:** Only individual Telegram user IDs included in `TELEGRAM_ALLOWED_USER_IDS` may read or change products; groups are not supported. An empty allowlist denies inventory access. Anyone who knows your bot's public username can open it, but cannot access inventory without being on the allowlist. Keep tokens secret. Existing `.env` files using the older `TELEGRAM_ALLOWED_IDS` setting remain supported.

The conversation combines text-message steps with inline-button callbacks. PTB's `per_message=False` warning is suppressed for this intentional setup; state remains scoped per user and private chat so the text steps and button responses stay in the same flow. Logs show command names and error classes only; they do not include message text, user IDs, or token values.

**Do not run `app.py` and `telegram_bot.py` at the same time** against the same file. This student project uses local JSON storage and does not support simultaneous writers. Run one interface, close it, then use the other. Telegram changes are visible in the CLI on its next launch.

## What is in the ZIP?

```text
COSC221_Telegram_Inventory_Final/
├── app.py                 # required command-line menu
├── inventory.py           # Product and InventoryManager classes; validation
├── storage.py             # robust JSON load / atomic save
├── telegram_bot.py        # optional Telegram bot menus and conversations
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
- The bot cannot answer when your laptop/computer is off, the process is stopped, or its internet connection is down. No cloud deployment is included.
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

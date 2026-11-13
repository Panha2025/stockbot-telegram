# Testing Report — COSC 221 Small Shop Inventory and Telegram Webhook

**Offline automated command:** `.venv/bin/python -m unittest discover -s tests -v`  
**Observed result:** **84 tests passed; 0 failures; 0 errors** on Python 3.13.15 with python-telegram-bot 22.8 in this environment. Python compilation and a CLI launch/exit smoke check also passed.

**Test safety:** Isolated temporary JSON files were used. SHA-256 checks confirmed `data/inventory.json` and `data/sample_inventory.json` are unchanged.

**Supabase:** Migration 003 was applied to the confirmed Supabase project. The four tables report RLS and FORCE RLS enabled, expected policies and runtime grants are present, and `anon`, `authenticated`, and `service_role` cannot read webhook state. A temporary two-account isolation test passed inside a rolled-back transaction; no test rows or temporary role membership remain.

**Webhook:** Mocked/in-process HTTP-handler tests verify invalid-secret rejection, duplicate-update acknowledgment, and ignoring group updates. Persistence tests verify conversation and user state survives new adapter instances and rejects other-account keys. A live Telegram webhook test is **not completed**.
**Vercel:** The project exists and the production public-mode settings are configured. The local Vercel build check could not run: automatic review rejected pulling project settings because that command could download production environment values into local files. No deployment was started.

## Required testing table (observed, automated)

| # | Input/action | Expected result | Actual observed result | Pass/fail |
|---|---|---|---|---|
| 1 | Add `Apple juice`, category Beverages, qty 8, price 2.50 | Unique product ID saved | Created P001 and reloaded correctly | PASS |
| 2 | Add with blank name/category | Reject empty required fields | Both rejected; no record stored | PASS |
| 3 | Add quantity -1, 3.5, text, or > 1,000,000 | Reject invalid quantity | All rejected | PASS |
| 4 | Add price -2, 2.999, or text | Reject invalid price | All rejected | PASS |
| 5 | Search for existing `PEN` / category `stationery` | Return matching item | Correct product returned | PASS |
| 6 | Search for absent `banana` | Empty result | Returned empty list | PASS |
| 7 | Update P001 quantity and price, then reload | Changes persisted | New values present after reload | PASS |
| 8 | Cancel delete when prompted `no` | Keep product | Product remained | PASS |
| 9 | Confirm delete with exact `YES` | Remove saved product | Product absent after reload | PASS |
| 10 | Restart manager after add | Load saved data | Product recovered from JSON | PASS |
| 11 | Start with missing data file | Open without error, zero items | Loaded empty state, no crash | PASS |
| 12 | Start with broken JSON | Explain error, preserve file | Raised DataFileError; text unchanged | PASS |
| 13 | Start with a damaged record structure | Explain error, preserve file | Rejected and preserved file | PASS |
| 14 | Summary for 2×$3.50, 10×$1.20, 0×$2.00 | 3 products, 12 units, 2 low-stock, $19.00 | All totals matched | PASS |
| 15 | Delete P002 and add another item | Never reuse product ID | New item used P003 | PASS |
| 16 | Update/delete unknown P999 | Show clear error | ProductNotFound raised | PASS |
| 17 | Simulate JSON save failure | Preserve memory and disk state | Both states unchanged | PASS |
| 18 | Load bundled ten products | 10 products, 145 units, 3 low stock, $349.30 | All summary values matched | PASS |
| 19 | CLI: add/search/summary/exit | Correct output and saves | Product and computed totals printed | PASS |
| 20 | CLI: invalid menu option/empty required field | Helpful message, program continues | Recovered and remained usable | PASS |
| 21 | Empty Telegram allowed IDs | Reject inventory access by default | `parse_allowed_ids('')` returned empty set | PASS |
| 22 | Parse `123, 456,123` | Unique numeric IDs | Returned {123,456} | PASS |
| 23 | Invalid allowlist `abc`, `0`, `-2`, etc. | Reject configuration | ValueError raised | PASS |
| 24 | Read .env comment + quoted value | Read key/value safely | Parsed string; ignored unrelated text | PASS |
| 25 | Page seven items with six per page | Second page shows only item 7 | Page count and item matched | PASS |
| 26 | Format summary for 2×$2.50 | Show 2 units and $5.00 | Both values present in message | PASS |
| 27 | Add product with explicit P017 ID, then duplicate P017 | Save unique ID; reject duplicate; preserve valid JSON and next ID | Reloaded P017; duplicate rejected; next generated ID P018 | PASS |
| 28 | Authorize user ID across private/group chats and empty allowlist | Only configured private users pass | Allowed private user passed; all other cases denied | PASS |
| 29 | Parse menu and malformed callback actions | Accept supported menu/page actions; reject unknown callback data | Valid actions accepted; unsupported actions rejected | PASS |
| 30 | Telegram handler receives unlisted user | Deny access before inventory response | Access denied; no inventory shown | PASS (mocked) |
| 31 | Telegram add receives valid and duplicate IDs | Accept valid ID; reject duplicate | P017 accepted, then duplicate rejected | PASS (mocked) |
| 32 | Telegram delete callback selects Cancel | Keep product and make no write | Product remained in memory and JSON | PASS (mocked) |
| 33 | Set low-stock limit to 2 and check quantity 3 | Configured threshold is reported and applied | Quantity 3 is not low stock; negative configuration rejected | PASS |
| 34 | `/myid` handler with empty allowlist and no inventory manager context | Return Telegram user ID without authorization | Returned ID using mocked update | PASS (mocked) |
| 35 | Telegram preflight with expected bot identity and no webhook | Make read-only checks and continue | `get_me` and `get_webhook_info` called; no delete API used | PASS (mocked) |
| 36 | Telegram preflight with configured webhook | Stop without changing webhook | Raised safe-stop error; no webhook deletion | PASS (mocked) |
| 37 | Telegram preflight with a different bot username | Reject wrong bot token identity | Raised identity error before webhook query | PASS (mocked) |
| 38 | Build PTB 22.8 application | Register `/myid` before conversation; handle expected warning | Application built, `/myid` is first group 0 handler, warning suppressed | PASS |
| 39 | Log `/search` with private arguments | Log command name only | `/search` logged; arguments absent | PASS (mocked) |
| 40 | Startup with missing or invalid token | Give clear diagnostic without disclosing token | Missing and invalid cases reported; fake token absent from output | PASS (mocked) |
| 41 | Resolve a blank process allowlist with a valid `.env` list | Use the `.env` value | `.env` used when process value was empty | PASS |
| 42 | Resolve a non-empty process allowlist | Process value has precedence | Process value selected | PASS |
| 43 | Resolve legacy `TELEGRAM_ALLOWED_IDS` setting | Keep backwards compatibility | Legacy key resolved from `.env` | PASS |
| 44 | Authorized `/start` handler | Display the main menu | Authorized user received the menu markup | PASS (mocked) |
| 45 | Summary with zero stock and multiple categories | Include out-of-stock count and category totals | Counts and category value calculated by InventoryManager | PASS |
| 46 | Generate ID with existing P001/P003 and next counter 4 | Select next unused ID and persist counter | Created P004 and reloaded it successfully | PASS |
| 47 | Add through preview and confirm | Save only after confirmation and show assigned ID | Created P001 only after Save; repeated Save did not create a second item | PASS (mocked) |
| 48 | Cancel add-product preview | Leave JSON unchanged | No product was created | PASS (mocked) |
| 49 | Choose preset and custom categories; submit invalid quantity/price | Offer all categories and reject invalid numeric input | Presets shown; custom category accepted; invalid quantity/price retried | PASS (mocked) |
| 50 | Delete selection and tap confirmation/cancel repeatedly | Require explicit confirmation; stale callback cannot repeat deletion | Cancel preserved item; confirmed deletion removed it once | PASS (mocked) |
| 51 | Browse 11 products | Show five products per page | Three pages; first page shows P001–P005 | PASS (mocked) |
| 52 | Search mixed-case partial query and no-match query | Find partial case-insensitive match; show retry on no results | Matching item shown; no-match message and retry button shown | PASS (mocked) |
| 53 | Edit quantity and tap save | Preview before persistence; retain product ID | Quantity changed after confirmation; ID remained stable | PASS (mocked) |
| 54 | Low-stock alert stock-update button | Allow selecting and updating a low-stock item | Button opened quantity update; quantity saved after confirmation | PASS (mocked) |
| 55 | Existing CLI and JSON tests | Keep CLI compatible with generated IDs and persistence | Full CLI/inventory test suite passed; bundled data unchanged | PASS |
| 56 | Edit product details in add preview | Validate edits and return to preview before save | Quantity revised in preview; saved only after confirmation | PASS (mocked) |

## Manual Telegram tests — team must complete these

**Do not mark a row PASS before testing it with a real bot account and a real Telegram connection.**

| Action | Expected result | Actual observed result | PASS / FAIL |
|---|---|---|---|
| Create bot with BotFather, run without allowlist, send `/myid` | Shows own numeric user ID; no access to inventory | [Team fills] | [ ] |
| Unauthorized Telegram user sends `/list` | Access denied without inventory details | [Team fills] | [ ] |
| Add own ID, restart, send `/start` | Menu and buttons appear | [Team fills] | [ ] |
| Press Add and enter valid name, category, qty, price | Creates unique ID, confirms saved product | [Team fills] | [ ] |
| Enter negative quantity or bad price | Clear error, prompts to retry | [Team fills] | [ ] |
| `/search Rice` / search nonexistent item | Shows matching items / no-results message | [Team fills] | [ ] |
| `/edit P001` and change quantity | Updates item, persists | [Team fills] | [ ] |
| `/delete P001` and select Cancel | Product remains | [Team fills] | [ ] |
| `/delete P001` and select Yes | Product removed | [Team fills] | [ ] |
| `/summary` and `/low` | Correct totals and low-stock items | [Team fills] | [ ] |
| Stop and restart bot, send `/list` | Previously saved updates still there | [Team fills] | [ ] |

## Known testing limitations

- No replacement Telegram token is configured yet, so bot identity, webhook delivery, `/start`, product CRUD, and Telegram's `getWebhookInfo` have not been tested live. After deployment, the owner must send `/start` from Telegram.
- PTB 22.8 application construction, command routing order, warning behavior, mocked preflight, handler flows, webhook HTTP handling, persistence restarts, Python compilation, and the CLI were exercised in the project `.venv`.
- Configuration resolver tests verify environment precedence, blank-value fallback, and legacy-key compatibility. A safe workspace check verified one valid `.env` ID without displaying it.
- Vercel build/deployment remains unverified. The GitHub repository connection also needs its GitHub App authorization completed in Vercel.

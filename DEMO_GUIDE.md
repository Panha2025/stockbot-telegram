# Live Demonstration Script (5–7 minutes)

## Before class

- Confirm the correct TeamXX and all names in README.
- Open project in VS Code and check `python3 app.py`.
- If showing Telegram, ensure your `.env` is **not** on screen, token is never shown, internet is working, bot is running in a *separate session*, and the student presenting is on the allowlist.
- **Never run CLI and Telegram together** while both can change the same JSON file. Use a copied test data file if you need to demonstrate a separate Telegram bot session.
- Have a backup plan: the **CLI alone** satisfies the project if Telegram is offline.

## Suggested flow

**0:00–0:40 — Introduce the problem and record fields.**
Explain that small shops need an inventory list; the one record type is ID, name, category, quantity, price.

**0:40–2:10 — Required operations in `app.py`.**
Show option 2 (ten products), option 1 (add a test product), option 3 (search for it), option 4 (update quantity).

**2:10–3:10 — Validation and safe deletion.**
Try adding negative quantity: show error. Delete a product but first say `no` to cancel, then type `YES` to confirm.

**3:10–4:00 — Summary and persistence.**
Show option 6 (product counts, total units, low-stock items and total value). Exit and restart: records remain. Explain JSON saves.

**4:00–5:10 — Explain Python architecture.**
Explain `Product`, `InventoryManager`, dictionary lookup by unique ID, and `InventoryStorage` with safe JSON writing. Point to the three separate files.

**5:10–6:10 — Optional Telegram (only if tested).**
Use `/start`, `/list`, `/summary`, or `/add`. For Add, show the category buttons, automatic ID preview, and Save/Cancel confirmation. Briefly explain that it reuses the same manager and requires Telegram ID access control.

**6:10–7:00 — Wrap up and questions.**
Every student explains the part they actually contributed. Mention no DB, no machine learning, and that the bot needs the local process running.

## Likely instructor questions

**Why a dictionary?** Unique IDs make product lookup and update simple.

**Why at least two classes?** One class represents a product, another class manages the collection and calculations.

**How do you save?** The manager calls storage after successful changes; storage writes a temporary JSON and atomically replaces the previous file.

**What happens with a damaged JSON file?** The app refuses to open it and warns the user, keeping the original file unchanged.

**Does Telegram replace the Python part?** No. It is a second user interface that calls the exact same Python manager.

**Why is the bot not public?** A user-ID allowlist prevents other Telegram users from viewing/editing a shop's products.

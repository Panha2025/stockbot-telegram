# Testing Report

Run the suite with the project's `.venv`:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests cover the CLI and its unchanged JSON inventory, product validation and CRUD, Telegram commands and buttons, public private-chat authorization, webhook-to-polling transition, per-user local JSON isolation, saved state across manager restarts, account deletion, file permissions, and the 500-product limit.

The Telegram API itself needs a valid token and network access. A live Telegram check should be done after starting the bot locally: send `/start` to `@SmallShopInventory221Bot`, add a test product, then use another Telegram account to confirm its inventory is separate.

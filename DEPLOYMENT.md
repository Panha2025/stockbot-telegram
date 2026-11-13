# StockBot public deployment (Supabase + Render)

This guide deploys the existing Telegram application as one long-polling Render background worker. The required CLI, `InventoryManager`, local JSON adapter, `data/inventory.json`, and fictional sample data remain local and unchanged. Public Telegram inventories are stored only in the separate Supabase PostgreSQL database.

## Before production

The old Telegram token was exposed and must not be reused. In Telegram, use the official `@BotFather` privately to revoke the old token and issue a replacement. Do not paste it into GitHub, this repository, a chat, or a log. Enter it only in Render's secret environment variable UI. You can use a different bot for staging.

You need owner access to a Supabase project and a Render account. Creating a paid worker or paid database plan may require billing details and authorization. This repository does not deploy anything until you create the cloud resources and set their secrets.

## 1. Create the database and role

1. Create a Supabase PostgreSQL project. Choose a nearby region and save the database owner's password privately.
2. In Supabase **SQL Editor**, open `migrations/001_public_inventory.sql`.
3. Before running it, replace the literal `REPLACE_WITH_A_LONG_RANDOM_PASSWORD` in the `CREATE ROLE` statement with a freshly generated, unique password. Never commit this edited migration. Run it as the project database owner.
4. In Supabase **Project Settings → Database → Connection string**, copy the PostgreSQL URI for the `stockbot_app` role. Use SSL; the application enforces `sslmode=require`. URL-encode special characters in the password when assembling a URI.
5. Store that URI only as Render's `DATABASE_URL`. Do not use the Supabase `service_role` API key. The database role has no table ownership or `BYPASSRLS`, and PostgreSQL row-level policies require the transaction-local verified Telegram ID set by the bot.

The migration creates `shop_users` and `shop_products`, per-user product IDs, exact `numeric(8,2)` prices, ownership indexes, foreign-key cascade, a repeated-confirmation idempotency key, and RLS policies. All application queries also include the Telegram account ID explicitly. No existing local inventory or sample product is copied to Supabase.

If this migration is ever reset or edited, back up the database first. For free Supabase projects, inactivity can pause the project and automatic backups are not included. Pro currently lists $25/month, includes $10/month of compute credits, does not pause for inactivity, and includes seven days of daily backups. Confirm current terms in the [Supabase pricing page](https://supabase.com/pricing) and [backup guide](https://supabase.com/docs/guides/platform/backups).

## 2. Create the Render worker

1. Push this repository to GitHub and connect `Panha2025/stockbot-telegram` to Render.
2. Choose **Blueprint** deployment and select this repository's `render.yaml`, or create a Background Worker manually using the same values: branch `main`, region `Singapore`, build command `pip install -r requirements.txt`, start command `python telegram_bot.py`, and the Starter compute plan.
3. Configure these environment variables in Render's dashboard. Mark token and database URL as secrets.

   | Variable | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | Replacement token from BotFather |
   | `DATABASE_URL` | SSL PostgreSQL URI for `stockbot_app` |
   | `BOT_ACCESS_MODE` | `public` |
   | `STORAGE_BACKEND` | `postgres` |
   | `LOW_STOCK_LIMIT` | `5` (or your chosen non-negative integer) |
   | `TELEGRAM_ADMIN_USER_IDS` | Optional comma-separated numeric IDs allowed to use `/status` |

4. Check Render's Blueprint review for the `starter` worker and required secret prompts. Apply the blueprint and wait for a successful deploy.
5. Confirm one worker instance is running. Never start a local bot with the same token while the worker is polling. Telegram permits only one active polling process for a bot token.

Render documents background workers as continuously running services. The current smallest paid worker compute tier is listed at $7/month (512 MB RAM); the free tier is not suitable for reliable 24/7 operation. Render Hobby workspaces currently add no workspace subscription fee, but usage, taxes, and terms can change. The rough baseline is Render $7/month plus Supabase Pro $25/month, before usage beyond included limits. Neither service plan gives this project a contractual uptime guarantee; actual service availability depends on Render, Supabase, Telegram, and networking. See [Render pricing](https://render.com/pricing) and [background workers](https://render.com/docs/background-workers).

## 3. Verify production

After deployment, check Render worker logs for startup, Telegram identity verification, clean database initialization, and polling. Logs intentionally omit token values, user IDs, and message text. With an ID configured in `TELEGRAM_ADMIN_USER_IDS`, send `/status` in a private chat to check the database connection.

Then send `/start` to the bot in a private Telegram chat. The first authorized `/start` creates an empty private account. Existing local sample records are not imported. Verify by adding a fictional test item, searching and updating it, then check from a second Telegram account that it does not appear there. Delete the test item afterward.

If a live Telegram test requires you to send `/start`, it must be sent by you from Telegram; deployment tooling cannot simulate your personal chat. A local test can conflict with Render polling, so stop the Render worker before briefly running a local polling instance and restart only one of them.

## Data, privacy, and retention

StockBot receives Telegram's account ID and the inventory fields users enter. Inventory data is retained in Supabase until the user uses `/deleteaccount` and confirms, or the database operator deletes it. `/deleteaccount` permanently removes that user's products and account row. Reopening `/start` creates a new empty inventory. Deleted records may remain in provider backups until those backups expire.

Each request comes from a private Telegram update and is bound to Telegram's numeric sender ID, never a user-supplied ID or callback field. Product reads and writes carry that owner ID and are also constrained by database RLS. Database credentials remain on the server. Input validation, parameterized SQL, a 60-update-per-minute per-user limit, a 500-product account cap, and unique callback idempotency keys are applied. Rate-limit state is in worker memory and resets on restart; the database product cap and RLS persist.

## Monitoring and recovery

- Review Render worker events and logs after deploys and periodically. Render restarts the worker after process failure; the application handles SIGINT/SIGTERM through python-telegram-bot's polling lifecycle and avoids deleting Telegram updates on startup.
- `/status` is available only to the numeric IDs listed in `TELEGRAM_ADMIN_USER_IDS`. It reports database connectivity only.
- If Render reports polling conflict, stop the duplicate worker/process. Do not keep two workers active with one bot token.
- Supabase Pro includes seven days of daily backups at the time this guide was written. Review the Supabase **Database → Backups** panel and periodically practice restoring a backup to a separate project before relying on it. Free plans lack automatic backups and may pause after one week of inactivity; they are not the recommended 24/7 configuration.
- For a restore, create/restore into a separate project first, verify schema and records, then update Render's `DATABASE_URL` and redeploy. Do not experiment against the only live database.
- No data migration is needed for existing local JSON. Keep local data backed up independently for university grading.

## Local public-mode smoke testing

Use a separate Supabase test project, a replacement/staging bot token, and `.env` excluded by `.gitignore`. Set `BOT_ACCESS_MODE=public`, `STORAGE_BACKEND=postgres`, `DATABASE_URL`, and `TELEGRAM_BOT_TOKEN`; install dependencies with `python -m pip install -r requirements.txt`. Do not connect tests to a production database. Use the automated mock suite for normal development.

# Free StockBot webhook deployment

This deployment keeps the COSC 221 CLI and its JSON files local. Telegram's webhook calls a Vercel Python Function; the function stores public bot data in Supabase PostgreSQL. It does not import or upload the fictional sample inventory.

## Free service limits

Vercel Python Functions are currently in Beta and available on Hobby, which has free monthly usage quotas. Hobby functions have finite duration limits; this project sets a 60-second maximum. Telegram sends a webhook update and receives a response, so the bot does not run a long-polling process. Hobby quotas, provider availability, and Supabase Free inactivity pauses can interrupt service. This is not guaranteed 24/7 hosting. Use Hobby only within Vercel's current personal, non-commercial plan terms. Do not upgrade or add a paid service for this project.

## Database

The existing Supabase project already has migrations `001_public_inventory`, `002_public_inventory_policy_acl_hardening`, and `003_vercel_webhook_runtime` applied. The four required tables are present with forced RLS, owner-scoped policies, and least-privilege grants for the non-superuser `stockbot_runtime` role. Do not rerun migrations or change role memberships for this project. If setting up a separate fresh database, follow the migration order in `migrations/` and verify the schema before deploying.

To audit the current project (read-only), run the following in Supabase SQL Editor:

```sql
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('shop_users', 'shop_products', 'shop_rate_limits', 'shop_webhook_updates')
ORDER BY c.relname;

SELECT tablename, policyname, cmd
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('shop_users', 'shop_products', 'shop_rate_limits', 'shop_webhook_updates')
ORDER BY tablename, policyname;

SELECT has_table_privilege('stockbot_runtime', 'public.shop_rate_limits', 'SELECT') AS runtime_can_select_rate_limits,
       has_table_privilege('stockbot_runtime', 'public.shop_webhook_updates', 'INSERT') AS runtime_can_claim_updates,
       has_table_privilege('anon', 'public.shop_webhook_updates', 'SELECT') AS anon_can_read_updates,
       has_table_privilege('authenticated', 'public.shop_webhook_updates', 'SELECT') AS authenticated_can_read_updates,
       has_table_privilege('service_role', 'public.shop_webhook_updates', 'SELECT') AS service_role_can_read_updates;
```

All four tables should report row security and forced row security as true. The new tables should have policies named `shop_rate_limits_owner_policy` and `shop_webhook_updates_owner_policy`; runtime should have its CRUD grants, while the three Supabase API roles should have no grants on these tables. Existing policies on `shop_users` and `shop_products` should remain unchanged. Do not run destructive cleanup queries.

### Private database credentials and TLS

1. In Supabase **Connect**, select the **Session pooler** and use its values for the database host, port, database name, and username. Use `stockbot_runtime.<project-ref>` as the username format if the dashboard specifies it. Do not use the `service_role` API key or project-owner password for the bot connection.
2. The current `stockbot_runtime` role has no password yet. Set a strong unique password through an interactive local `psql` session using `\password stockbot_runtime`, and save it in a password manager. If the Supabase `postgres` password is unavailable, reset it in the Supabase Database Settings first, then use the new value only at the hidden `psql` password prompt. Do not put either password in SQL, shell history, Git, or this guide.
3. Download the Supabase database root certificate from the project settings. Keep it in a private local path. Convert its contents to one-line base64 for Vercel's encrypted environment variable:

   ```bash
   base64 < /path/to/supabase-root.crt | tr -d '\n'
   ```

   Paste that output directly into Vercel's private `DATABASE_SSL_ROOT_CERT_B64` environment variable. The function writes the certificate to a mode-0600 temporary file and uses PostgreSQL `sslmode=verify-full`.
4. Build `DATABASE_URL` from the Session pooler host, port, database, `stockbot_runtime.<project-ref>` username, and the password encoded for a URI. Store it only as a Vercel encrypted environment variable. Do not print it or put it in `.env.example`.

The serverless adapter opens short-lived connections per update with a 10-second connect timeout and full TLS verification. Do not use a direct database endpoint if the deployment network cannot reach it; use the Supabase Session pooler values. Keep `DATABASE_SSL_ROOT_CERT_B64` and `DATABASE_URL` out of GitHub.

### Optional import of existing local Telegram inventories

Local per-user inventory files, when present, are in the ignored `data/telegram_users/` folder. They are not included in a Git push or Vercel deployment. The importer reads these files but never edits or removes them; it also excludes the CLI's `data/inventory.json` and sample data.

To migrate them, first set `DATABASE_URL` and `DATABASE_SSL_ROOT_CERT` privately in your local `.env` and keep the certificate file outside Git. Run a dry run:

```bash
.venv/bin/python scripts/import_local_telegram_data.py
```

If the report confirms the data and all destination accounts are empty, run:

```bash
.venv/bin/python scripts/import_local_telegram_data.py --apply
```

The import runs in one database transaction and aborts without writing if any destination Telegram account already exists. Run it before people begin using the hosted bot. It reports only totals, not Telegram IDs or product details.

## Vercel project

1. Reuse the existing Vercel Hobby project `stockbot-telegram` (`stockbot-telegram.vercel.app`). It is currently not connected to Git and has no production deployment. Connect it to `Panha2025/stockbot-telegram`, branch `main`, with the project root as the root directory. The repository includes `api/telegram.py`, `vercel.json`, `requirements.txt`, and `.vercelignore`.
2. Keep the account on the **Hobby** plan. Do not add paid compute, payment details, or a subscription.
3. Add these private production environment variables in **Project → Settings → Environment Variables**:

   | Name | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | A newly issued token from BotFather; revoke the previously exposed token first. Never reuse it. |
   | `TELEGRAM_WEBHOOK_SECRET` | New random URL-safe string of 32+ characters. |
   | `DATABASE_URL` | Runtime-role Supabase Session pooler connection URI. |
   | `DATABASE_SSL_ROOT_CERT_B64` | One-line base64 of Supabase's database root certificate. |
   | `BOT_ACCESS_MODE` | `public` |
   | `STORAGE_BACKEND` | `postgres` |
   | `LOW_STOCK_LIMIT` | `5` |
   | `TELEGRAM_ADMIN_USER_IDS` | Optional comma-separated numeric IDs permitted to use `/status`. |

   Mark credentials and certificate data as **Sensitive/Secret**, restrict them to **Production**, and never add them as `NEXT_PUBLIC_` variables. After changing any value, redeploy Production so the function receives it. Do not paste any secret into chat or commit it.
4. Deploy. The public endpoint is `https://<your-vercel-domain>/api/telegram`. A GET health check should return `{"ok":true}`. Do not configure the Telegram webhook until all production secrets are present and the health check succeeds.

## Register Telegram webhook

The old token was exposed. Revoke it with the official `@BotFather`, then issue a replacement. Store it in Vercel's private production variable. In a local terminal with the project `.venv` active, run:

```bash
.venv/bin/python scripts/register_webhook.py
```

The script prompts for the Vercel endpoint, then reads the replacement token and webhook secret with masked input. Enter the exact `https://<your-vercel-domain>/api/telegram` endpoint. The script registers Telegram's `secret_token` header and `message`/`callback_query` updates, and prints only webhook status details. It does not print the token or secret. The webhook secret must exactly match `TELEGRAM_WEBHOOK_SECRET` in Vercel. Telegram will send the secret in `X-Telegram-Bot-Api-Secret-Token`.

If the deployed Vercel environment does not yet contain the matching token and secret, stop and set those values in Vercel first. Never use Telegram long polling while a webhook is registered. Local development polling checks for an existing webhook and stops rather than removing it.

## Verify

1. Open the Vercel deployment and check its `/api/telegram` health endpoint.
2. Run the registration script and confirm `getWebhookInfo` reports the expected endpoint and no recent delivery error. The output excludes credentials.
3. Send `/start` to `@SmallShopInventory221Bot` from Telegram. A live end-to-end check requires you to send that message yourself.
4. Add, view, search, update, delete a test product, check summary and low-stock alerts, then use `/deleteaccount` and confirm. A second Telegram account should see an empty, separate inventory.
5. Check Vercel function logs for generic status/errors only. Never log payloads, user IDs, message text, tokens, database URLs, or certificate contents.

Conversation form state, per-user rate limits, and Telegram update claims live in Supabase, not process memory, so cold starts and redelivery do not reset a flow or duplicate a completed update. An update that fails during processing can be retried by Telegram. Supabase retains each user's products until they confirm `/deleteaccount` or an operator deletes the database record.

## Local course CLI and local bot

The required command-line application remains independent of this deployment and continues to use `data/inventory.json`:

```bash
.venv/bin/python app.py
```

Local JSON Telegram mode remains available for a restricted allowlist and local demonstration. Set private values in `.env` and run `.venv/bin/python telegram_bot.py`. Do not run local polling with the production bot token while its webhook is registered. Never commit `.env`, database credentials, TLS certificates, or real user data.

Run automated tests with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Vercel Hobby and Supabase Free are subject to current provider terms, quotas, and pauses. Neither guarantees continuous service or automatic backups. Check current plans before deployment and do not upgrade without a separate decision to change the $0/month requirement.

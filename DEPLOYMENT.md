# Free StockBot webhook deployment

This deployment keeps the COSC 221 CLI and its JSON files local. Telegram's webhook calls a Vercel Python Function; the function stores public bot data in Supabase PostgreSQL. It does not import or upload the fictional sample inventory.

## Free service limits

Vercel Python Functions are currently in Beta and available on Hobby, which has free monthly usage quotas. Hobby functions have finite duration limits; this project sets a 60-second maximum. Telegram sends a webhook update and receives a response, so the bot does not run a long-polling process. Hobby quotas, provider availability, and Supabase Free inactivity pauses can interrupt service. This is not guaranteed 24/7 hosting. Use Hobby only within Vercel's current personal, non-commercial plan terms. Do not upgrade or add a paid service for this project.

## Database

Migrations `001_public_inventory.sql` and `002_public_inventory_policy_acl_hardening.sql` create the inventory schema, the non-superuser `stockbot_runtime` role, least-privilege grants, and forced owner-scoped RLS. Migration `003_vercel_webhook_runtime.sql` adds per-account Telegram conversation state, rate limits, and update de-duplication. It is additive and safe to rerun; it does not drop or clear existing data. Run the complete SQL from migration 003 in Supabase SQL Editor after confirming migrations 001 and 002 are already present. Do not change the role memberships or disable RLS.

After running migration 003, verify the following in Supabase SQL Editor:

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

1. In Supabase **Connect**, select the **Session pooler** and use its values for the database host, port, database name, and username. Use `stockbot_runtime.<project-ref>` as the username format if the dashboard specifies it. Do not use the `service_role` API key or project-owner password.
2. If no password has been set for `stockbot_runtime`, use the Supabase owner's secure local `psql` connection and the interactive `\password stockbot_runtime` prompt. Generate and save a strong unique password in a password manager. Do not put it in SQL, shell history, Git, or this guide.
3. Download the Supabase database root certificate from the project settings. Keep it in a private local path. Convert its contents to one-line base64 for Vercel's encrypted environment variable:

   ```bash
   base64 < /path/to/supabase-root.crt | tr -d '\n'
   ```

   Paste that output directly into Vercel's private `DATABASE_SSL_ROOT_CERT_B64` environment variable. The function writes the certificate to a mode-0600 temporary file and uses PostgreSQL `sslmode=verify-full`.
4. Build `DATABASE_URL` from the Session pooler host, port, database, `stockbot_runtime.<project-ref>` username, and the password encoded for a URI. Store it only as a Vercel encrypted environment variable. Do not print it or put it in `.env.example`.

The serverless adapter opens short-lived connections per update with a 10-second connect timeout and full TLS verification. Do not use a direct database endpoint if the deployment network cannot reach it; use the Supabase Session pooler values. Keep `DATABASE_SSL_ROOT_CERT_B64` and `DATABASE_URL` out of GitHub.

## Vercel project

1. Sign in to Vercel and create a project by importing `Panha2025/stockbot-telegram`. Select branch `main`; use the project root as the root directory. The repository includes `api/telegram.py`, `vercel.json`, `requirements.txt`, and `.vercelignore`.
2. Choose the **Hobby** plan and verify the deployment review shows no paid add-on, paid compute, or paid subscription before confirming. Do not enter payment details or upgrade.
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

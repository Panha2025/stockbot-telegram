# StockBot public deployment (Supabase + Render)

This guide deploys the existing Telegram application as one long-polling Render background worker. The required CLI, `InventoryManager`, local JSON adapter, `data/inventory.json`, and fictional sample data remain local and unchanged. Public Telegram inventories are stored only in the separate Supabase PostgreSQL database.

## Before production

The old Telegram token was exposed and must not be reused. In Telegram, use the official `@BotFather` privately to revoke the old token and issue a replacement. Do not paste it into GitHub, this repository, a chat, or a log. Enter it only in Render's secret environment variable UI. You can use a different bot for staging.

You need owner access to a Supabase project and a Render account. Creating a paid worker or paid database plan may require billing details and authorization. This repository does not deploy anything until you create the cloud resources and set their secrets.

## 1. Create the database and role

1. Keep the project-owner password separate from the bot's app-role password. In Supabase **Project Settings → Database → SSL Configuration**, download the database root certificate and save it locally.
2. First run the **read-only audit query** below in a new Supabase SQL Editor query. The previous failed migration may have left some objects in place, depending on how the SQL Editor transaction was handled. Review the role output: the revised migration deliberately ignores `stockbot_app` and uses a separate `stockbot_runtime` role. Do not reuse or alter an existing role reported as elevated.
3. If the audit shows no `stockbot_runtime` role, or shows a login role with no elevated flags and no unexpected memberships, paste and run `migrations/001_public_inventory.sql` first, then paste and run `migrations/002_public_inventory_policy_acl_hardening.sql`. PostgreSQL 16+ automatically grants the role creator an admin membership in a newly created role with `INHERIT` and `SET ROLE` disabled; the first migration accepts only that `postgres` membership and rejects any other membership. Both scripts are safe to rerun and do not drop tables or delete rows. If either aborts, stop and inspect the audit results rather than changing or deleting database objects.
4. Set the app-role password interactively so it never appears in SQL source, browser query history, or the shell command. On your Mac, use `psql` with the direct connection details from Supabase **Connect** (or its **Session pooler** details if direct IPv6 is unavailable). Run `psql 'host=<HOST_FROM_CONNECT> port=<PORT_FROM_CONNECT> dbname=postgres user=<OWNER_USERNAME_FROM_CONNECT> sslmode=verify-full sslrootcert=<LOCAL_ROOT_CERT_PATH>'`. This command contains no password; `psql` prompts for the project owner's password. At the `psql` prompt, run `\password stockbot_runtime`, enter a freshly generated long random password from your password manager when prompted, then enter it again to confirm. Save it in that password manager and type `\q` to exit. The `\password` prompt hides the new value and keeps it out of command history.
5. In Supabase **Connect**, choose **Session pooler** for a Render worker on an IPv4-only network. Copy the complete URI and substitute the custom-role username `stockbot_runtime.<PROJECT_REF>` and the app-role password. Use the pooler host and port exactly as shown. Percent-encode any reserved characters in the password for the URI.
6. In Render, open the worker's **Environment** page, choose **Add Secret File**, set the filename to `supabase-ca.crt`, and paste in the downloaded root certificate file contents. Set `DATABASE_SSL_ROOT_CERT` to `/etc/secrets/supabase-ca.crt`. Store the completed URI only in Render's `DATABASE_URL` secret. The app verifies the server certificate with `sslmode=verify-full`. Do not use the Supabase `service_role` API key or the project-owner database password. The runtime role has no table ownership or `BYPASSRLS`, and PostgreSQL row-level policies require the transaction-local verified Telegram ID set by the bot.

### Read-only check before migration

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('shop_users', 'shop_products')
ORDER BY table_name;

SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('shop_users', 'shop_products')
ORDER BY c.relname;

SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
       rolinherit, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname IN ('stockbot_app', 'stockbot_runtime')
ORDER BY rolname;

SELECT member_role.rolname AS member_role, granted_role.rolname AS granted_role
FROM pg_auth_members AS m
JOIN pg_roles AS member_role ON member_role.oid = m.member
JOIN pg_roles AS granted_role ON granted_role.oid = m.roleid
WHERE member_role.rolname IN ('stockbot_app', 'stockbot_runtime')
   OR granted_role.rolname IN ('stockbot_app', 'stockbot_runtime');

SELECT tablename, policyname, permissive, cmd, roles, qual, with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('shop_users', 'shop_products')
ORDER BY tablename, policyname;
```

The old role is not used by the revised migration. Do not change it based only on its name; the audit reports its attributes without revealing any password. If `stockbot_runtime` exists with elevated attributes or role memberships, do not run the migration until its ownership and purpose are understood.

After clicking **Run** on the migration, Supabase should show a successful result. To verify the schema, create another SQL Editor query and run:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('shop_users', 'shop_products')
ORDER BY table_name;

SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('shop_users', 'shop_products')
ORDER BY c.relname;

SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
       rolinherit, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname = 'stockbot_runtime';

SELECT granted_role.rolname AS granted_role, member_role.rolname AS member_role,
       m.admin_option, m.inherit_option, m.set_option
FROM pg_auth_members AS m
JOIN pg_roles AS member_role ON member_role.oid = m.member
JOIN pg_roles AS granted_role ON granted_role.oid = m.roleid
WHERE member_role.rolname = 'stockbot_runtime'
   OR granted_role.rolname = 'stockbot_runtime';

SELECT
  has_table_privilege('stockbot_runtime', 'public.shop_products', 'SELECT') AS app_can_select,
  has_table_privilege('stockbot_runtime', 'public.shop_products', 'INSERT') AS app_can_insert,
  has_table_privilege('stockbot_runtime', 'public.shop_products', 'UPDATE') AS app_can_update,
  has_table_privilege('stockbot_runtime', 'public.shop_products', 'DELETE') AS app_can_delete,
  has_table_privilege('anon', 'public.shop_products', 'SELECT') AS anon_can_select,
  has_table_privilege('authenticated', 'public.shop_products', 'SELECT') AS authenticated_can_select,
  has_table_privilege('service_role', 'public.shop_products', 'SELECT') AS service_role_can_select,
  has_table_privilege('service_role', 'public.shop_products', 'TRUNCATE') AS service_role_can_truncate;

SELECT tablename, policyname, cmd, qual, with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('shop_users', 'shop_products')
ORDER BY tablename, policyname;

SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name IN ('shop_users', 'shop_products')
ORDER BY table_name, grantee, privilege_type;
```

Expected: both tables are listed; both have `relrowsecurity` and `relforcerowsecurity` set to `true`; `stockbot_runtime` has login enabled and `rolsuper`, `rolcreatedb`, `rolcreaterole`, `rolinherit`, `rolreplication`, and `rolbypassrls` set to `false`; the four app privilege columns are `true`, while `PUBLIC`, `anon`, `authenticated`, and `service_role` have no table privileges; and each table has its owner policy. The only accepted role-membership row is `stockbot_runtime` granted to `postgres` with `admin_option=true`, `inherit_option=false`, and `set_option=false`. The policy expressions should compare `telegram_user_id` with the transaction setting `app.telegram_user_id`. The migration does not add sample inventory rows.

The migrations create `shop_users` and `shop_products`, per-user product IDs, exact `numeric(8,2)` prices, ownership indexes, foreign-key cascade, a repeated-confirmation idempotency key, and RLS policies. The hardening migration also removes Supabase's default `service_role` table ACLs from these bot-owned tables. All application queries also include the Telegram account ID explicitly. No existing local inventory or sample product is copied to Supabase.

If this migration is ever reset or edited, back up the database first. For free Supabase projects, inactivity can pause the project and automatic backups are not included. Pro currently lists $25/month, includes $10/month of compute credits, does not pause for inactivity, and includes seven days of daily backups. Confirm current terms in the [Supabase pricing page](https://supabase.com/pricing) and [backup guide](https://supabase.com/docs/guides/platform/backups).

## 2. Create the Render worker

1. Push this repository to GitHub and connect `Panha2025/stockbot-telegram` to Render.
2. Choose **Blueprint** deployment and select this repository's `render.yaml`, or create a Background Worker manually using the same values: branch `main`, region `Singapore`, build command `pip install -r requirements.txt`, start command `python telegram_bot.py`, and the Starter compute plan.
3. Configure these environment variables in Render's dashboard. Mark token and database URL as secrets.

   | Variable | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | Replacement token from BotFather |
   | `DATABASE_URL` | SSL PostgreSQL URI for `stockbot_runtime` |
   | `DATABASE_SSL_ROOT_CERT` | `/etc/secrets/supabase-ca.crt` (upload the certificate as a Render secret file) |
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

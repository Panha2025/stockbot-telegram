-- Tighten Supabase's default service_role table ACL and cache the RLS setting
-- once per query. Safe to rerun; does not remove tables, rows, or policies.
BEGIN;

ALTER POLICY shop_users_owner_policy ON public.shop_users
    TO public
    USING (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint))
    WITH CHECK (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint));

ALTER POLICY shop_products_owner_policy ON public.shop_products
    TO public
    USING (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint))
    WITH CHECK (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint));

REVOKE ALL ON public.shop_users, public.shop_products
    FROM PUBLIC, anon, authenticated, service_role;

COMMIT;

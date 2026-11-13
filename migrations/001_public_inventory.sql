-- Run as the Supabase database owner in the SQL editor.
-- The bot connects as a separate, non-owner role and is subject to RLS.
CREATE TABLE IF NOT EXISTS public.shop_users (
    telegram_user_id bigint PRIMARY KEY CHECK (telegram_user_id > 0),
    next_product_number bigint NOT NULL DEFAULT 1 CHECK (next_product_number > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.shop_products (
    telegram_user_id bigint NOT NULL REFERENCES public.shop_users(telegram_user_id) ON DELETE CASCADE,
    product_id text NOT NULL CHECK (product_id ~ '^P[0-9]{3,}$'),
    name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 80),
    category text NOT NULL CHECK (char_length(btrim(category)) BETWEEN 1 AND 40),
    quantity integer NOT NULL CHECK (quantity BETWEEN 0 AND 1000000),
    price numeric(8,2) NOT NULL CHECK (price BETWEEN 0 AND 999999.99),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    idempotency_key text CHECK (idempotency_key IS NULL OR idempotency_key ~ '^[A-Za-z0-9_-]{1,32}$'),
    PRIMARY KEY (telegram_user_id, product_id),
    UNIQUE (telegram_user_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS shop_products_owner_name_idx
    ON public.shop_products (telegram_user_id, lower(name));
CREATE INDEX IF NOT EXISTS shop_products_owner_category_idx
    ON public.shop_products (telegram_user_id, lower(category));

ALTER TABLE public.shop_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shop_users FORCE ROW LEVEL SECURITY;
ALTER TABLE public.shop_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shop_products FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shop_users_owner_policy ON public.shop_users;
CREATE POLICY shop_users_owner_policy ON public.shop_users
    USING (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
    WITH CHECK (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint);
DROP POLICY IF EXISTS shop_products_owner_policy ON public.shop_products;
CREATE POLICY shop_products_owner_policy ON public.shop_products
    USING (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
    WITH CHECK (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint);

-- Replace the password before running this statement. Keep it server-side.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'stockbot_app') THEN
        EXECUTE format('CREATE ROLE stockbot_app LOGIN PASSWORD %L', 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD');
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO stockbot_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.shop_users, public.shop_products TO stockbot_app;
REVOKE ALL ON public.shop_users, public.shop_products FROM anon, authenticated;

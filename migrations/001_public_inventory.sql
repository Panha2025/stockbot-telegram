-- Safe to rerun. Run as the Supabase database owner in SQL Editor.
-- This migration never drops tables, rows, roles, indexes, or policies.
BEGIN;

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

-- A different role name avoids altering or granting access to any pre-existing
-- stockbot_app role. The runtime role is created without a password; set it
-- later using psql's interactive \password command.
DO $$
DECLARE
    role_attrs record;
BEGIN
    SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit,
           rolreplication, rolbypassrls
      INTO role_attrs
      FROM pg_roles
     WHERE rolname = 'stockbot_runtime';

    IF NOT FOUND THEN
        EXECUTE 'CREATE ROLE stockbot_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS';
    ELSIF NOT role_attrs.rolcanlogin
       OR role_attrs.rolsuper
       OR role_attrs.rolcreatedb
       OR role_attrs.rolcreaterole
       OR role_attrs.rolinherit
       OR role_attrs.rolreplication
       OR role_attrs.rolbypassrls THEN
        RAISE EXCEPTION 'Existing stockbot_runtime role has unexpected privileges; inspect it before continuing';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM pg_auth_members AS membership
          JOIN pg_roles AS parent_role ON parent_role.oid = membership.roleid
          JOIN pg_roles AS member_role ON member_role.oid = membership.member
         WHERE member_role.rolname = 'stockbot_runtime'
            OR parent_role.rolname = 'stockbot_runtime'
    ) THEN
        RAISE EXCEPTION 'Existing stockbot_runtime has role memberships; inspect them before continuing';
    END IF;
END;
$$;

-- Do not silently coexist with additional policies: permissive policies are
-- ORed together and could accidentally widen access.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'shop_users'
           AND policyname <> 'shop_users_owner_policy'
    ) OR EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'shop_products'
           AND policyname <> 'shop_products_owner_policy'
    ) THEN
        RAISE EXCEPTION 'Unexpected policy exists on StockBot tables; inspect policies before continuing';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'shop_users'
           AND policyname = 'shop_users_owner_policy' AND (permissive <> 'PERMISSIVE' OR cmd <> 'ALL')
    ) OR EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'shop_products'
           AND policyname = 'shop_products_owner_policy' AND (permissive <> 'PERMISSIVE' OR cmd <> 'ALL')
    ) THEN
        RAISE EXCEPTION 'Existing StockBot owner policy is restrictive; inspect it before continuing';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'shop_users'
           AND policyname = 'shop_users_owner_policy'
    ) THEN
        EXECUTE $policy$
            ALTER POLICY shop_users_owner_policy ON public.shop_users TO public
            USING (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
            WITH CHECK (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
        $policy$;
    ELSE
        EXECUTE $policy$
            CREATE POLICY shop_users_owner_policy ON public.shop_users TO public
            USING (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
            WITH CHECK (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
        $policy$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'shop_products'
           AND policyname = 'shop_products_owner_policy'
    ) THEN
        EXECUTE $policy$
            ALTER POLICY shop_products_owner_policy ON public.shop_products TO public
            USING (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
            WITH CHECK (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
        $policy$;
    ELSE
        EXECUTE $policy$
            CREATE POLICY shop_products_owner_policy ON public.shop_products TO public
            USING (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
            WITH CHECK (telegram_user_id = nullif(current_setting('app.telegram_user_id', true), '')::bigint)
        $policy$;
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA public TO stockbot_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.shop_users, public.shop_products TO stockbot_runtime;
REVOKE ALL ON public.shop_users, public.shop_products FROM PUBLIC, anon, authenticated;

COMMIT;

-- Durable state, request limits, and webhook de-duplication for stateless hosts.
-- Additive and rerunnable; it does not remove existing inventory data or policies.
BEGIN;

ALTER TABLE public.shop_users
    ADD COLUMN IF NOT EXISTS bot_user_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS bot_conversations jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS public.shop_rate_limits (
    telegram_user_id bigint PRIMARY KEY REFERENCES public.shop_users(telegram_user_id) ON DELETE CASCADE,
    window_started_at timestamptz NOT NULL DEFAULT now(),
    request_count integer NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.shop_webhook_updates (
    update_id bigint PRIMARY KEY,
    telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
    status text NOT NULL CHECK (status IN ('processing', 'done', 'failed')),
    attempts integer NOT NULL DEFAULT 1 CHECK (attempts > 0),
    started_at timestamptz NOT NULL DEFAULT now(),
    received_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE INDEX IF NOT EXISTS shop_webhook_updates_owner_received_idx
    ON public.shop_webhook_updates (telegram_user_id, received_at);

ALTER TABLE public.shop_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shop_rate_limits FORCE ROW LEVEL SECURITY;
ALTER TABLE public.shop_webhook_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shop_webhook_updates FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename IN ('shop_rate_limits', 'shop_webhook_updates')
          AND policyname NOT IN ('shop_rate_limits_owner_policy', 'shop_webhook_updates_owner_policy')
    ) THEN
        RAISE EXCEPTION 'Unexpected policy exists on StockBot webhook tables';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'shop_rate_limits'
          AND policyname = 'shop_rate_limits_owner_policy'
    ) THEN
        CREATE POLICY shop_rate_limits_owner_policy ON public.shop_rate_limits TO public
            USING (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint))
            WITH CHECK (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'shop_webhook_updates'
          AND policyname = 'shop_webhook_updates_owner_policy'
    ) THEN
        CREATE POLICY shop_webhook_updates_owner_policy ON public.shop_webhook_updates TO public
            USING (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint))
            WITH CHECK (telegram_user_id = (SELECT nullif(current_setting('app.telegram_user_id', true), '')::bigint));
    END IF;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.shop_rate_limits, public.shop_webhook_updates TO stockbot_runtime;
REVOKE ALL ON public.shop_rate_limits, public.shop_webhook_updates FROM PUBLIC, anon, authenticated, service_role;

COMMIT;

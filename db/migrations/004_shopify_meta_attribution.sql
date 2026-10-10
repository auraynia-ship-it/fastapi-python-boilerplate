CREATE TABLE IF NOT EXISTS public.shopify_meta_attribution (
    cart_token_hash CHAR(64) PRIMARY KEY,
    fbc TEXT,
    fbp TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS shopify_meta_attribution_expires_at_idx
    ON public.shopify_meta_attribution (expires_at);

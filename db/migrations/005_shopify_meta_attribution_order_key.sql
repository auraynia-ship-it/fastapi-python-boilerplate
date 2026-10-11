ALTER TABLE public.shopify_meta_attribution
    RENAME COLUMN cart_token_hash TO attribution_key_hash;

ALTER TABLE public.shopify_meta_attribution
    ADD COLUMN IF NOT EXISTS key_type VARCHAR(16) NOT NULL DEFAULT 'cart',
    ADD COLUMN IF NOT EXISTS shop_domain VARCHAR(255),
    ADD COLUMN IF NOT EXISTS order_id VARCHAR(255);

ALTER TABLE public.shopify_meta_attribution
    ADD CONSTRAINT shopify_meta_attribution_key_type_check
    CHECK (key_type IN ('cart', 'order'));

CREATE UNIQUE INDEX IF NOT EXISTS shopify_meta_attribution_order_key_idx
    ON public.shopify_meta_attribution (shop_domain, order_id)
    WHERE key_type = 'order' AND order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS shopify_meta_attribution_key_type_expires_idx
    ON public.shopify_meta_attribution (key_type, expires_at);

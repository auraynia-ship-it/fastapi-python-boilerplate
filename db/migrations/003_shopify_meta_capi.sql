ALTER TABLE public.shopify_webhook_events
    ADD COLUMN IF NOT EXISTS meta_status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS meta_event_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS meta_value NUMERIC(18, 2),
    ADD COLUMN IF NOT EXISTS meta_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS meta_response JSONB,
    ADD COLUMN IF NOT EXISTS meta_error TEXT,
    ADD COLUMN IF NOT EXISTS meta_sent_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS shopify_webhook_events_meta_status_idx
    ON public.shopify_webhook_events (meta_status, received_at);

-- Give every application table (except app_migrations) consistent timestamps
-- while preserving the best available age for existing rows.
ALTER TABLE public.shipment_edd_job_runs
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
UPDATE public.shipment_edd_job_runs
SET updated_at = COALESCE(updated_at, created_at, started_at, now());
ALTER TABLE public.shipment_edd_job_runs
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE public.shipment_snapshots
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
UPDATE public.shipment_snapshots
SET created_at = COALESCE(created_at, updated_at, now());
ALTER TABLE public.shipment_snapshots
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE public.shipment_edd_breaches
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
UPDATE public.shipment_edd_breaches
SET updated_at = COALESCE(updated_at, created_at, breach_date::timestamptz, now());
ALTER TABLE public.shipment_edd_breaches
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE public.shopify_webhook_events
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
UPDATE public.shopify_webhook_events
SET created_at = COALESCE(created_at, received_at, now()),
    updated_at = COALESCE(updated_at, processed_at, received_at, now());
ALTER TABLE public.shopify_webhook_events
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE public.shopify_meta_attribution
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
UPDATE public.shopify_meta_attribution
SET created_at = COALESCE(created_at, updated_at, now());
ALTER TABLE public.shopify_meta_attribution
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL;

CREATE OR REPLACE FUNCTION public.touch_retention_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS shipment_edd_job_runs_touch_updated_at ON public.shipment_edd_job_runs;
CREATE TRIGGER shipment_edd_job_runs_touch_updated_at
BEFORE UPDATE ON public.shipment_edd_job_runs
FOR EACH ROW EXECUTE FUNCTION public.touch_retention_updated_at();

DROP TRIGGER IF EXISTS shipment_edd_breaches_touch_updated_at ON public.shipment_edd_breaches;
CREATE TRIGGER shipment_edd_breaches_touch_updated_at
BEFORE UPDATE ON public.shipment_edd_breaches
FOR EACH ROW EXECUTE FUNCTION public.touch_retention_updated_at();

DROP TRIGGER IF EXISTS shopify_webhook_events_touch_updated_at ON public.shopify_webhook_events;
CREATE TRIGGER shopify_webhook_events_touch_updated_at
BEFORE UPDATE ON public.shopify_webhook_events
FOR EACH ROW EXECUTE FUNCTION public.touch_retention_updated_at();

DROP TRIGGER IF EXISTS shopify_meta_attribution_touch_updated_at ON public.shopify_meta_attribution;
CREATE TRIGGER shopify_meta_attribution_touch_updated_at
BEFORE UPDATE ON public.shopify_meta_attribution
FOR EACH ROW EXECUTE FUNCTION public.touch_retention_updated_at();

CREATE INDEX IF NOT EXISTS shipment_edd_job_runs_created_at_idx
    ON public.shipment_edd_job_runs (created_at);
CREATE INDEX IF NOT EXISTS shipment_edd_breaches_created_at_idx
    ON public.shipment_edd_breaches (created_at);
CREATE INDEX IF NOT EXISTS shipment_snapshots_created_at_idx
    ON public.shipment_snapshots (created_at);
CREATE INDEX IF NOT EXISTS shopify_webhook_events_created_at_idx
    ON public.shopify_webhook_events (created_at);
CREATE INDEX IF NOT EXISTS shopify_meta_attribution_created_at_idx
    ON public.shopify_meta_attribution (created_at);

NOTIFY pgrst, 'reload schema';

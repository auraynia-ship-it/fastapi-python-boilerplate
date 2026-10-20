CREATE TABLE IF NOT EXISTS public.shipment_movement_concern_job_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name text NOT NULL DEFAULT 'shipment_movement_concern',
    status text NOT NULL,
    dry_run boolean NOT NULL DEFAULT false,
    awb_only boolean NOT NULL DEFAULT false,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    orders_fetched integer NOT NULL DEFAULT 0,
    shipments_checked integer NOT NULL DEFAULT 0,
    movement_concerns_found integer NOT NULL DEFAULT 0,
    report_csv_path text,
    report_blob_url text,
    awb_codes text[] NOT NULL DEFAULT '{}',
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.shipment_movement_concerns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_run_id uuid NOT NULL REFERENCES public.shipment_movement_concern_job_runs(id) ON DELETE CASCADE,
    concern_date date NOT NULL,
    awb_code text NOT NULL,
    severity text NOT NULL,
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    edd date,
    days_until_edd integer,
    days_since_last_movement integer,
    last_movement_date date,
    shiprocket_order_id text,
    channel_order_id text,
    shipment_id text,
    courier_name text,
    status text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_run_id, awb_code)
);

CREATE INDEX IF NOT EXISTS shipment_movement_concerns_awb_date_idx
    ON public.shipment_movement_concerns (awb_code, concern_date);

NOTIFY pgrst, 'reload schema';

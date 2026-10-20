ALTER TABLE public.shipment_edd_job_runs
    ADD COLUMN IF NOT EXISTS dry_run boolean NOT NULL DEFAULT false;

NOTIFY pgrst, 'reload schema';

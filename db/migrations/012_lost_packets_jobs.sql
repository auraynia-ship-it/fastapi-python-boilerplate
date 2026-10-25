CREATE TABLE IF NOT EXISTS public.lost_packets_job_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status text NOT NULL,
    from_date date NOT NULL,
    to_date date NOT NULL,
    per_page integer NOT NULL DEFAULT 100,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    fetched_orders integer NOT NULL DEFAULT 0,
    lost_packets_count integer NOT NULL DEFAULT 0,
    result jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lost_packets_job_runs_created_at_idx
    ON public.lost_packets_job_runs (created_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.lost_packets_job_runs TO service_role;

NOTIFY pgrst, 'reload schema';

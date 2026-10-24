-- Supabase no longer grants Data API access automatically to newly created
-- public tables. Keep server-side access explicit for tables used by this app.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.app_migrations,
    public.shipment_edd_job_runs,
    public.shipment_snapshots,
    public.shipment_edd_breaches,
    public.shopify_webhook_events,
    public.shopify_meta_attribution,
    public.shipment_movement_concern_job_runs,
    public.shipment_movement_concerns,
    public.shipment_status_summary_job_runs,
    public.discounted_orders_job_runs
TO service_role;

GRANT USAGE, SELECT ON SEQUENCE public.shopify_webhook_events_id_seq TO service_role;

NOTIFY pgrst, 'reload schema';

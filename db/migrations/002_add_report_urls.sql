alter table public.shipment_edd_job_runs
    add column if not exists report_csv_path text,
    add column if not exists report_pdf_path text,
    add column if not exists report_blob_url text;

notify pgrst, 'reload schema';


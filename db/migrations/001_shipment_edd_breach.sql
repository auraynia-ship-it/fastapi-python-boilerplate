create extension if not exists pgcrypto;

create table if not exists public.shipment_edd_job_runs (
    id uuid primary key default gen_random_uuid(),
    job_name text not null default 'shipment_edd_breach',
    status text not null,
    started_at timestamptz not null,
    completed_at timestamptz,
    orders_fetched integer not null default 0,
    shipments_checked integer not null default 0,
    breaches_found integer not null default 0,
    report_path text,
    awb_codes text[] not null default '{}',
    error_message text,
    created_at timestamptz not null default now()
);

create table if not exists public.shipment_snapshots (
    awb_code text primary key,
    shiprocket_order_id text,
    channel_order_id text,
    shipment_id text,
    courier_name text,
    status text,
    edd date,
    delivered_date date,
    rto_initiated_date date,
    last_checked_date date not null,
    raw_payload jsonb not null,
    updated_at timestamptz not null default now()
);

create table if not exists public.shipment_edd_breaches (
    id uuid primary key default gen_random_uuid(),
    job_run_id uuid references public.shipment_edd_job_runs(id) on delete set null,
    awb_code text not null references public.shipment_snapshots(awb_code) on delete cascade,
    breach_date date not null,
    edd date not null,
    days_delayed integer not null,
    shiprocket_order_id text,
    channel_order_id text,
    shipment_id text,
    courier_name text,
    status text,
    delivered_date date,
    rto_initiated_date date,
    raw_payload jsonb not null,
    created_at timestamptz not null default now(),
    unique (awb_code, breach_date)
);

create index if not exists shipment_snapshots_last_checked_date_idx
    on public.shipment_snapshots(last_checked_date);

create index if not exists shipment_snapshots_edd_idx
    on public.shipment_snapshots(edd);

create index if not exists shipment_edd_breaches_breach_date_idx
    on public.shipment_edd_breaches(breach_date);

create or replace function public.touch_shipment_snapshot_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists shipment_snapshots_touch_updated_at on public.shipment_snapshots;

create trigger shipment_snapshots_touch_updated_at
before update on public.shipment_snapshots
for each row
execute function public.touch_shipment_snapshot_updated_at();


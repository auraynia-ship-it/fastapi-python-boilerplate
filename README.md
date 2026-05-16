[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fvercel%2Fexamples%2Ftree%2Fmain%2Fpython%2Ffastapi&demo-title=FastAPI&demo-description=Use%20FastAPI%20on%20Vercel%20with%20Serverless%20Functions%20using%20the%20Python%20Runtime.&demo-url=https%3A%2F%2Fvercel-plus-fastapi.vercel.app%2F&demo-image=https://assets.vercel.com/image/upload/v1669994600/random/python.png)

# FastAPI + Vercel

This example shows how to use FastAPI on Vercel with Serverless Functions using the [Python Runtime](https://vercel.com/docs/concepts/functions/serverless-functions/runtimes/python).

## Shipment EDD Breach Job

The app includes a daily Shiprocket EDD breach job at:

```bash
GET /api/jobs/edd-breach/run
```

You can also trigger the same task manually from the API docs with:

```bash
POST /api/shipments/edd-breaches/run
```

Operational checks:

```bash
GET /api/shipments/edd-breaches/health
POST /api/shipments/edd-breaches/db/migrate
```

The health endpoint verifies Supabase config, Supabase REST reachability, required
`public` tables, and Shiprocket credentials. The migration endpoint applies
pending SQL files from `db/migrations/` using `POSTGRES_URL_NON_POOLING` or
`POSTGRES_URL`, and records successful filenames in `public.app_migrations`.

Vercel runs it every day at `03:30 UTC` / `09:00 IST` through `vercel.json`.

The job:

- fetches Shiprocket orders for the configured lookback window
- extracts shipment/AWB data from each order
- flags a breach when `today > edd`, `delivered_date` is empty, and `rto_initiated_date` is empty
- writes a CSV report under `reports/` locally or `/tmp/shipment_edd_reports` on Vercel
- prints breached AWBs in the server logs
- stores job runs, latest shipment snapshots, and daily breach rows in Supabase

Run this SQL in Supabase before enabling the cron:

```text
db/migrations/001_shipment_edd_breach.sql
```

Tables created:

- `shipment_edd_job_runs`: one row per job execution, counts, report path, and breached AWBs
- `shipment_snapshots`: latest known state per AWB, including EDD/delivery/RTO dates and raw Shiprocket payload
- `shipment_edd_breaches`: one row per AWB per breach date, including delay days and useful order/shipment metadata

Useful environment variables:

```bash
SHIPROCKET_TOKEN=
SHIPROCKET_EMAIL=
SHIPROCKET_PASSWORD=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
EDD_JOB_CRON_SECRET=
EDD_JOB_TIMEZONE=Asia/Kolkata
SHIPROCKET_ORDER_WINDOW_DAYS=45
SHIPROCKET_MAX_PAGES=20
SHIPROCKET_PER_PAGE=100
EDD_REPORT_DIR=reports
```

For Shiprocket auth, either provide `SHIPROCKET_TOKEN` directly or provide both
`SHIPROCKET_EMAIL` and `SHIPROCKET_PASSWORD` for an API user so the app can log
in and refresh the token automatically.

For local testing:

```bash
curl "http://localhost:3000/api/jobs/edd-breach/run?dry_run=true"
curl -X POST "http://localhost:3000/api/shipments/edd-breaches/run?dry_run=true"
curl "http://localhost:3000/api/shipments/edd-breaches/health"
curl -X POST "http://localhost:3000/api/shipments/edd-breaches/db/migrate"
```

If `EDD_JOB_CRON_SECRET` or `CRON_SECRET` is set, call the endpoint with:

```bash
Authorization: Bearer <secret>
```

## Demo

https://vercel-plus-fastapi.vercel.app/

## How it Works

This example uses the Asynchronous Server Gateway Interface (ASGI) with FastAPI to enable handling requests on Vercel with Serverless Functions.

## Running Locally

```bash
npm i -g vercel
vercel dev
```

Your FastAPI application is now available at `http://localhost:3000`.

## One-Click Deploy

Deploy the example using [Vercel](https://vercel.com?utm_source=github&utm_medium=readme&utm_campaign=vercel-examples):

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fvercel%2Fexamples%2Ftree%2Fmain%2Fpython%2Ffastapi&demo-title=FastAPI&demo-description=Use%20FastAPI%20on%20Vercel%20with%20Serverless%20Functions%20using%20the%20Python%20Runtime.&demo-url=https%3A%2F%2Fvercel-plus-fastapi.vercel.app%2F&demo-image=https://assets.vercel.com/image/upload/v1669994600/random/python.png)

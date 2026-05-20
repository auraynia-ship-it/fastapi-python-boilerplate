[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fvercel%2Fexamples%2Ftree%2Fmain%2Fpython%2Ffastapi&demo-title=FastAPI&demo-description=Use%20FastAPI%20on%20Vercel%20with%20Serverless%20Functions%20using%20the%20Python%20Runtime.&demo-url=https%3A%2F%2Fvercel-plus-fastapi.vercel.app%2F&demo-image=https://assets.vercel.com/image/upload/v1669994600/random/python.png)

Run these in PowerShell:
Get-Process python | Stop-Process -Force
python -m uvicorn main:app --host 127.0.0.1 --port 8000

Then open:
http://127.0.0.1:8000/docs

If you want it to keep running in the background:
Start-Process -FilePath python -ArgumentList '-m','uvicorn','main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory 'c:\Users\hpsma\fastapi-python-boilerplate' -WindowStyle Hidden


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

### Vercel Routing

On Vercel, the FastAPI app is served from `api/index.py`, so:

- API base: `/api`
- Swagger UI: `/api/docs`
- OpenAPI JSON: `/api/openapi.json`

The root URL `/` is a static page (`public/index.html`) that redirects to `/api/docs`.

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
EDD_JOB_TIMEZONE=Asia/Kolkata
SHIPROCKET_ORDER_WINDOW_DAYS=45
SHIPROCKET_MAX_PAGES=20
SHIPROCKET_PER_PAGE=100
EDD_REPORT_DIR=reports
EDD_REPORT_BLOB_PREFIX=edd-breach-reports
EDD_REPORT_BLOB_ACCESS=public
BLOB_READ_WRITE_TOKEN=
LOG_LEVEL=INFO
```

For Shiprocket auth, either provide `SHIPROCKET_TOKEN` directly or provide both
`SHIPROCKET_EMAIL` and `SHIPROCKET_PASSWORD` for an API user so the app can log
in and refresh the token automatically.

For Vercel deployments, set `SHIPROCKET_EMAIL` and `SHIPROCKET_PASSWORD` in the
Vercel project environment variables for Production, Preview, and Development as
needed. The local `.env` file is only used on your machine and is not deployed to
Vercel. Prefer credentials over a pasted `SHIPROCKET_TOKEN`, because Shiprocket
tokens expire and the app can only refresh them when both credentials are
available.

The EDD breach run creates a PDF report for every completed non-dry run,
including days with zero breaches. If `BLOB_READ_WRITE_TOKEN` is configured, the
PDF is uploaded to Vercel Blob and the API response includes `report_blob_url`.
Dry runs skip blob uploads.

Blob uploads use Vercel Blob's HTTP API directly, so they do not depend on the
Python Vercel SDK being installed. Redeploy after changing code or environment
variables.

Useful log lines to check in Vercel Runtime Logs after triggering the job:

- `edd_breach_job_started` shows whether blob config is present.
- `edd_breach_reports_created` shows the CSV/PDF paths created by the run.
- `edd_breach_blob_upload_skipped` shows the exact skip reason.
- `edd_breach_blob_upload_completed` includes the uploaded blob URL.

For local testing:

```bash
curl "http://localhost:3000/api/jobs/edd-breach/run?dry_run=true"
curl -X POST "http://localhost:3000/api/shipments/edd-breaches/run?dry_run=true"
curl "http://localhost:3000/api/shipments/edd-breaches/health"
curl -X POST "http://localhost:3000/api/shipments/edd-breaches/db/migrate"
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

import json
import logging
import os
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool

from shipment_edd.config import get_edd_job_settings, load_env_file
from shipment_edd.health import check_edd_system_health, run_edd_migration
from shipment_edd.job import run_edd_breach_job
from shipment_edd.shiprocket import ShiprocketClient, ShiprocketError
from fastapi.responses import HTMLResponse


load_env_file()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Vercel + FastAPI",
    description="Vercel + FastAPI",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://auraynia.com",
        "https://www.auraynia.com",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def get_shiprocket_client():
    settings = get_edd_job_settings()
    return ShiprocketClient(
        token=settings.shiprocket_token,
        email=settings.shiprocket_email,
        password=settings.shiprocket_password,
        timeout=20,
    )


@app.get("/api/serviceability")
def get_serviceability_date(
    pickup_postcode: str = Query(...),
    delivery_postcode: str = Query(...),
    weight: float = Query(..., ge=0.5),
    cod: int = Query(..., ge=0, le=1),
):
    logger.info(
        "serviceability_request pickup_postcode=%s delivery_postcode=%s weight=%s cod=%s",
        pickup_postcode,
        delivery_postcode,
        weight,
        cod,
    )
    try:
        response_data = get_shiprocket_client().fetch_serviceability(
            pickup_postcode=pickup_postcode,
            delivery_postcode=delivery_postcode,
            weight=weight,
            cod=cod,
        )
    except ShiprocketError as error:
        message = str(error)
        status_code = 503 if "SHIPROCKET_" in message else 502
        logger.warning(
            "serviceability_failed status_code=%s error=%s",
            status_code,
            message,
        )
        raise HTTPException(status_code=status_code, detail=message) from error

    courier_companies = (
        response_data.get("data", {}).get("available_courier_companies", [])
    )
    etd_dates = []
    for courier in courier_companies:
        etd = courier.get("etd")
        if not etd:
            continue

        try:
            etd_dates.append(datetime.strptime(etd, "%b %d, %Y").date())
        except ValueError:
            continue

    if not etd_dates:
        raise HTTPException(
            status_code=404,
            detail="No valid etd found in available courier companies.",
        )

    earliest_etd = min(etd_dates)
    return {"date": (earliest_etd + timedelta(days=1)).isoformat()}


@app.get("/api/jobs/edd-breach/run", include_in_schema=False)
async def run_shipment_edd_breach_job(
    dry_run: bool = Query(False),
):
    return await execute_shipment_edd_breach_job(dry_run)


@app.post("/api/shipments/edd-breaches/run", summary="Run Shipment EDD Breach Job")
async def run_shipment_edd_breach_job_endpoint(
    dry_run: bool = Query(False),
):
    return await execute_shipment_edd_breach_job(dry_run)


@app.get("/api/db/health", summary="Check Shipment EDD System Health")
def check_shipment_edd_health():
    return check_edd_system_health()


@app.post("/api/db/migrate", summary="Run Shipment EDD DB Migration")
def run_shipment_edd_db_migration():
    try:
        return run_edd_migration()
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Shipment EDD migration failed: {error}",
        ) from error


async def execute_shipment_edd_breach_job(
    dry_run: bool,
):
    logger.info("edd_breach_endpoint_called dry_run=%s", dry_run)
    try:
        result = await run_in_threadpool(run_edd_breach_job, dry_run=dry_run)
        logger.info(
            "edd_breach_endpoint_completed dry_run=%s breaches_found=%s report_blob_url_present=%s",
            dry_run,
            result.get("breaches_found"),
            bool(result.get("report_blob_url")),
        )
        logger.info(
            "edd_breach_endpoint_response=%s",
            json.dumps(result, default=str, ensure_ascii=True),
        )
        return result
    except Exception as error:
        logger.exception("edd_breach_endpoint_failed dry_run=%s", dry_run)
        raise HTTPException(
            status_code=502,
            detail=f"Shipment EDD breach job failed: {error}",
        ) from error

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Vercel + FastAPI</title>
        <link rel="icon" type="image/x-icon" href="/favicon.ico">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
                background-color: #000000;
                color: #ffffff;
                line-height: 1.6;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
            }
            
            header {
                border-bottom: 1px solid #333333;
                padding: 0;
            }
            
            nav {
                max-width: 1200px;
                margin: 0 auto;
                display: flex;
                align-items: center;
                padding: 1rem 2rem;
                gap: 2rem;
            }
            
            .logo {
                font-size: 1.25rem;
                font-weight: 600;
                color: #ffffff;
                text-decoration: none;
            }
            
            .nav-links {
                display: flex;
                gap: 1.5rem;
                margin-left: auto;
            }
            
            .nav-links a {
                text-decoration: none;
                color: #888888;
                padding: 0.5rem 1rem;
                border-radius: 6px;
                transition: all 0.2s ease;
                font-size: 0.875rem;
                font-weight: 500;
            }
            
            .nav-links a:hover {
                color: #ffffff;
                background-color: #111111;
            }
            
            main {
                flex: 1;
                max-width: 1200px;
                margin: 0 auto;
                padding: 4rem 2rem;
                display: flex;
                flex-direction: column;
                align-items: center;
                text-align: center;
            }
            
            .hero {
                margin-bottom: 3rem;
            }
            
            .hero-code {
                margin-top: 2rem;
                width: 100%;
                max-width: 900px;
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            }
            
            .hero-code pre {
                background-color: #0a0a0a;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 1.5rem;
                text-align: left;
                grid-column: 1 / -1;
            }
            
            h1 {
                font-size: 3rem;
                font-weight: 700;
                margin-bottom: 1rem;
                background: linear-gradient(to right, #ffffff, #888888);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            }
            
            .subtitle {
                font-size: 1.25rem;
                color: #888888;
                margin-bottom: 2rem;
                max-width: 600px;
            }
            
            .cards {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 1.5rem;
                width: 100%;
                max-width: 900px;
            }
            
            .card {
                background-color: #111111;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 1.5rem;
                transition: all 0.2s ease;
                text-align: left;
            }
            
            .card:hover {
                border-color: #555555;
                transform: translateY(-2px);
            }
            
            .card h3 {
                font-size: 1.125rem;
                font-weight: 600;
                margin-bottom: 0.5rem;
                color: #ffffff;
            }
            
            .card p {
                color: #888888;
                font-size: 0.875rem;
                margin-bottom: 1rem;
            }
            
            .card a {
                display: inline-flex;
                align-items: center;
                color: #ffffff;
                text-decoration: none;
                font-size: 0.875rem;
                font-weight: 500;
                padding: 0.5rem 1rem;
                background-color: #222222;
                border-radius: 6px;
                border: 1px solid #333333;
                transition: all 0.2s ease;
            }
            
            .card a:hover {
                background-color: #333333;
                border-color: #555555;
            }
            
            .status-badge {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                background-color: #0070f3;
                color: #ffffff;
                padding: 0.25rem 0.75rem;
                border-radius: 20px;
                font-size: 0.75rem;
                font-weight: 500;
                margin-bottom: 2rem;
            }
            
            .status-dot {
                width: 6px;
                height: 6px;
                background-color: #00ff88;
                border-radius: 50%;
            }
            
            pre {
                background-color: #0a0a0a;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 1rem;
                overflow-x: auto;
                margin: 0;
            }
            
            code {
                font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', Consolas, 'Courier New', monospace;
                font-size: 0.85rem;
                line-height: 1.5;
                color: #ffffff;
            }
            
            /* Syntax highlighting */
            .keyword {
                color: #ff79c6;
            }
            
            .string {
                color: #f1fa8c;
            }
            
            .function {
                color: #50fa7b;
            }
            
            .class {
                color: #8be9fd;
            }
            
            .module {
                color: #8be9fd;
            }
            
            .variable {
                color: #f8f8f2;
            }
            
            .decorator {
                color: #ffb86c;
            }
            
            @media (max-width: 768px) {
                nav {
                    padding: 1rem;
                    flex-direction: column;
                    gap: 1rem;
                }
                
                .nav-links {
                    margin-left: 0;
                }
                
                main {
                    padding: 2rem 1rem;
                }
                
                h1 {
                    font-size: 2rem;
                }
                
                .hero-code {
                    grid-template-columns: 1fr;
                }
                
                .cards {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    </head>
    <body>
        <header>
            <nav>
                <a href="/" class="logo">Vercel + FastAPI</a>
                <div class="nav-links">
                    <a href="/docs">API Docs</a>
                    <a href="/api/data">API</a>
                </div>
            </nav>
        </header>
        <main>
            <div class="hero">
                <h1>Vercel + FastAPI</h1>
                <div class="hero-code">
                    <pre><code><span class="keyword">from</span> <span class="module">fastapi</span> <span class="keyword">import</span> <span class="class">FastAPI</span>

<span class="variable">app</span> = <span class="class">FastAPI</span>()

<span class="decorator">@app.get</span>(<span class="string">"/"</span>)
<span class="keyword">def</span> <span class="function">read_root</span>():
    <span class="keyword">return</span> {<span class="string">"Python"</span>: <span class="string">"on Vercel"</span>}</code></pre>
                </div>
            </div>
            
            <div class="cards">
                <div class="card">
                    <h3>Interactive API Docs</h3>
                    <p>Explore this API's endpoints with the interactive Swagger UI. Test requests and view response schemas in real-time.</p>
                    <a href="/docs">Open Swagger UI →</a>
                </div>
                
                <div class="card">
                    <h3>Sample Data</h3>
                    <p>Access sample JSON data through our REST API. Perfect for testing and development purposes.</p>
                    <a href="/api/data">Get Data →</a>
                </div>
                
            </div>
        </main>
    </body>
    </html>
    """

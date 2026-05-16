import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from shipment_edd.config import get_edd_job_settings, load_env_file
from shipment_edd.health import check_edd_system_health, run_edd_migration
from shipment_edd.job import run_edd_breach_job


load_env_file()


SHIPROCKET_SERVICEABILITY_URL = (
    "https://apiv2.shiprocket.in/v1/external/courier/serviceability/"
)
SHIPROCKET_LOGIN_URL = "https://apiv2.shiprocket.in/v1/external/auth/login"
SHIPROCKET_TOKEN = os.getenv(
    "SHIPROCKET_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOjEwMzU4NTczLCJzb3VyY2UiOiJzci1hdXRoLWludCIsImV4cCI6MTc3OTE5OTA3NCwianRpIjoiM1dwaERrUEtQaWd4NHZrUCIsImlhdCI6MTc3ODMzNTA3NCwiaXNzIjoiaHR0cHM6Ly9zci1hdXRoLnNoaXByb2NrZXQuaW4vYXV0aG9yaXplL3VzZXIiLCJuYmYiOjE3NzgzMzUwNzQsImNpZCI6NzcyMDcwMywidGMiOjM2MCwidmVyYm9zZSI6ZmFsc2UsInZlbmRvcl9pZCI6MCwidmVuZG9yX2NvZGUiOiIifQ.RRB5gLy8cvsxyoFqbkn0eCOj1EA9tQTeg6_AFqARB1U",
)
SHIPROCKET_EMAIL = os.getenv("SHIPROCKET_EMAIL", "tarunbhatia35@gmail.com")
SHIPROCKET_PASSWORD = os.getenv("SHIPROCKET_PASSWORD")


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


def refresh_token():
    global SHIPROCKET_TOKEN

    if not SHIPROCKET_EMAIL or not SHIPROCKET_PASSWORD:
        raise HTTPException(
            status_code=500,
            detail="SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD are required to refresh token.",
        )

    payload = json.dumps(
        {
            "email": SHIPROCKET_EMAIL,
            "password": SHIPROCKET_PASSWORD,
        }
    ).encode("utf-8")
    request = Request(
        SHIPROCKET_LOGIN_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8") if error.fp else error.reason
        raise HTTPException(status_code=error.code, detail=detail) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to refresh Shiprocket  token: {error}",
        ) from error

    token = response_data.get("token")
    if not token:
        raise HTTPException(
            status_code=502,
            detail="Shiprocket login response did not include a token.",
        )

    SHIPROCKET_TOKEN = token
    os.environ["SHIPROCKET_TOKEN"] = token
    return token


def fetch_serviceability(query_params):
    request = Request(
        f"{SHIPROCKET_SERVICEABILITY_URL}?{query_params}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SHIPROCKET_TOKEN}",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 401:
            refresh_token()
            retry_request = Request(
                f"{SHIPROCKET_SERVICEABILITY_URL}?{query_params}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {SHIPROCKET_TOKEN}",
                },
                method="GET",
            )
            try:
                with urlopen(retry_request, timeout=20) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as retry_error:
                detail = (
                    retry_error.read().decode("utf-8")
                    if retry_error.fp
                    else retry_error.reason
                )
                raise HTTPException(
                    status_code=retry_error.code,
                    detail=detail,
                ) from retry_error
            except (URLError, TimeoutError, json.JSONDecodeError) as retry_error:
                raise HTTPException(
                    status_code=502,
                    detail=f"Unable to fetch serviceability data after refreshing token: {retry_error}",
                ) from retry_error

        detail = error.read().decode("utf-8") if error.fp else error.reason
        raise HTTPException(status_code=error.code, detail=detail) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to fetch serviceability data: {error}",
        ) from error


@app.get("/api/serviceability")
def get_serviceability_date(
    pickup_postcode: str = Query(...),
    delivery_postcode: str = Query(...),
    weight: float = Query(..., ge=0.5),
    cod: int = Query(..., ge=0, le=1),
):
    query_params = urlencode(
        {
            "pickup_postcode": pickup_postcode,
            "delivery_postcode": delivery_postcode,
            "weight": weight,
            "cod": cod,
        }
    )
    response_data = fetch_serviceability(query_params)

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
def run_shipment_edd_breach_job(
    dry_run: bool = Query(False),
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
):
    return execute_shipment_edd_breach_job(dry_run, authorization, x_cron_secret)


@app.post("/api/shipments/edd-breaches/run", summary="Run Shipment EDD Breach Job")
def run_shipment_edd_breach_job_endpoint(
    dry_run: bool = Query(False),
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
):
    return execute_shipment_edd_breach_job(dry_run, authorization, x_cron_secret)


@app.get("/api/db/health", summary="Check Shipment EDD System Health")
def check_shipment_edd_health():
    return check_edd_system_health()


@app.post("/api/db/migrate", summary="Run Shipment EDD DB Migration")
def run_shipment_edd_db_migration(
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
):
    validate_job_secret(authorization, x_cron_secret)

    try:
        return run_edd_migration()
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Shipment EDD migration failed: {error}",
        ) from error


def execute_shipment_edd_breach_job(
    dry_run: bool,
    authorization: str | None,
    x_cron_secret: str | None,
):
    validate_job_secret(authorization, x_cron_secret)

    try:
        return run_edd_breach_job(dry_run=dry_run)
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Shipment EDD breach job failed: {error}",
        ) from error


def validate_job_secret(
    authorization: str | None,
    x_cron_secret: str | None,
):
    settings = get_edd_job_settings()
    if settings.cron_secret:
        bearer = f"Bearer {settings.cron_secret}"
        if authorization != bearer and x_cron_secret != settings.cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron secret.")

import json
import logging
import os
import base64
import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool

from app.config.settings import get_edd_job_settings, load_env_file
from app.health.edd import check_edd_system_health, run_edd_migration
from app.cron_jobs.shipment_edd import (
    run_edd_breach_job,
    run_shipment_movement_concern_job,
)
from app.cron_jobs.data_retention import run_data_retention_job
from app.shipment_edd.shiprocket import ShiprocketClient, ShiprocketError
from app.database.supabase import SupabaseRestClient
from app.notifications.shipment_status_email import send_shipment_status_summary_email
from fastapi.responses import HTMLResponse, JSONResponse, Response
from app.shopify.meta import (
    MetaDeliveryError,
    get_browser_purchase_data,
    process_shopify_webhook,
    save_meta_attribution,
)


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
        "https://account.auraynia.com",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.post("/api/notifications/email/test", include_in_schema=True)
def send_email_test(x_email_test_token: str | None = Header(None)):
    settings = get_edd_job_settings()
    if not settings.email_test_endpoint_token:
        raise HTTPException(status_code=404, detail="Not found")
    if not x_email_test_token or not hmac.compare_digest(
        x_email_test_token, settings.email_test_endpoint_token
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        sent = send_shipment_status_summary_email(
            settings,
            "smtp-test",
            {},
            test=True,
        )
    except Exception as error:
        logger.exception("shipment_status_summary_smtp_test_failed")
        raise HTTPException(
            status_code=502,
            detail=f"SMTP test failed ({type(error).__name__}). Check server logs for details.",
        ) from error
    if not sent:
        raise HTTPException(status_code=503, detail="Email settings or recipients are missing")
    return {"status": "sent", "recipients": "configured recipient list"}


@app.middleware("http")
async def allow_shopify_pixel_opaque_origin(request: Request, call_next):
    """Allow Shopify's opaque sandbox origin only for Meta pixel helper routes."""
    pixel_paths = {
        "/api/meta/browser-purchase-lookup",
        "/api/meta/browser-attribution",
    }
    if (
        request.url.path not in pixel_paths
        or request.headers.get("origin", "").strip().lower() != "null"
    ):
        return await call_next(request)

    cors_headers = {
        "Access-Control-Allow-Origin": "null",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "content-type",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }

    if request.method == "OPTIONS":
        requested_method = request.headers.get(
            "access-control-request-method", ""
        ).upper()
        requested_headers = {
            header.strip().lower()
            for header in request.headers.get(
                "access-control-request-headers", ""
            ).split(",")
            if header.strip()
        }
        if requested_method != "POST" or not requested_headers.issubset({"content-type"}):
            return Response(status_code=400)
        return Response(status_code=204, headers=cors_headers)

    response = await call_next(request)
    response.headers.update(cors_headers)
    return response


def get_shiprocket_client():
    settings = get_edd_job_settings()
    return ShiprocketClient(
        token=settings.shiprocket_token,
        email=settings.shiprocket_email,
        password=settings.shiprocket_password,
        timeout=20,
    )


SHIPMENT_STATUS_BUCKETS = {
    "rto": "RTO",
    "delivered": "DELIVERED",
    "in_transit": "TRANSIT",
}


def order_has_channel_sku(order, channel_sku):
    if not channel_sku:
        return True

    sku_values = channel_sku if isinstance(channel_sku, (list, tuple, set)) else [channel_sku]
    expected_skus = {str(value).strip().casefold() for value in sku_values if str(value).strip()}
    if not expected_skus:
        return False
    products = order.get("products", [])
    if not isinstance(products, list):
        return False

    for product in products:
        if not isinstance(product, dict):
            continue
        product_sku = str(product.get("channel_sku", "")).strip().casefold()
        if product_sku in expected_skus:
            return True

    return False


def classify_shipment_status(status):
    normalized_status = str(status or "").upper()
    for bucket, keyword in SHIPMENT_STATUS_BUCKETS.items():
        if keyword in normalized_status:
            return bucket
    return None


def summarize_packets_by_status(orders, channel_sku):
    summary = {
        "delivered": 0,
        "rto": 0,
        "in_transit": 0,
    }
    ignored_statuses = {}
    rto_statuses = {}
    matched_packets = 0

    for order in orders:
        if not isinstance(order, dict) or not order_has_channel_sku(order, channel_sku):
            continue

        matched_packets += 1
        bucket = classify_shipment_status(order.get("status"))
        if bucket:
            summary[bucket] += 1
            if bucket == "rto":
                status = str(order.get("status") or "UNKNOWN").strip()
                rto_statuses[status] = rto_statuses.get(status, 0) + 1
            continue

        status = str(order.get("status") or "UNKNOWN")
        ignored_statuses[status] = ignored_statuses.get(status, 0) + 1

    return summary, matched_packets, ignored_statuses, rto_statuses


def parse_shipment_status_summary_skus(raw_value):
    """Parse comma-separated display-name:channel-sku entries."""
    configured_skus = []
    for entry in (raw_value or "").split(","):
        name, separator, channel_sku = entry.partition(":")
        name = name.strip()
        channel_sku = channel_sku.strip()
        if name and separator and channel_sku:
            configured_skus.append({"name": name, "channel_sku": channel_sku})
    return configured_skus


def group_shipment_status_summary_skus(configured_skus):
    grouped = {}
    for configured_sku in configured_skus:
        grouped.setdefault(configured_sku["name"], []).append(configured_sku["channel_sku"])
    return grouped


def summarize_shopify_order_payload(payload):
    line_items = payload.get("line_items", [])
    if not isinstance(line_items, list):
        line_items = []

    return {
        "order_id": payload.get("id"),
        "order_name": payload.get("name"),
        "order_number": payload.get("order_number"),
        "email_present": bool(payload.get("email")),
        "financial_status": payload.get("financial_status"),
        "fulfillment_status": payload.get("fulfillment_status"),
        "total_price": payload.get("total_price"),
        "currency": payload.get("currency"),
        "line_items_count": len(line_items),
    }


def verify_shopify_webhook_hmac(raw_body: bytes, hmac_header: str, secret: str) -> bool:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    calculated = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(calculated, hmac_header)


def get_order_discount(order):
    """Read common Shiprocket/Shopify order-level discount representations."""
    others = order.get("others") if isinstance(order.get("others"), dict) else {}
    for key in ("discount", "discount_amount", "total_discount", "discount_total"):
        value = order.get(key)
        if value not in (None, ""):
            try:
                amount = float(value)
                if amount > 0:
                    return amount
            except (TypeError, ValueError):
                continue

    # Shopify payloads may expose discounts on line items or discount applications.
    line_items = order.get("line_items")
    if isinstance(line_items, list):
        total = 0.0
        found = False
        for item in line_items:
            if not isinstance(item, dict):
                continue
            allocations = item.get("discount_allocations")
            if isinstance(allocations, list):
                for allocation in allocations:
                    if isinstance(allocation, dict):
                        try:
                            total += float(allocation.get("amount") or 0)
                            found = True
                        except (TypeError, ValueError):
                            pass
        if found:
            if total > 0:
                return total

    products = order.get("products")
    if isinstance(products, list):
        total = 0.0
        found = False
        for product in products:
            if not isinstance(product, dict):
                continue
            value = product.get("discount_including_tax")
            if value in (None, ""):
                value = product.get("discount")
            amount = parse_order_amount(value)
            if amount is not None and amount > 0:
                total += amount
                found = True
        if found:
            return round(total, 2)

    discount_codes = others.get("discount_codes")
    if isinstance(discount_codes, list):
        total = sum(
            amount
            for code in discount_codes
            if isinstance(code, dict)
            if (amount := parse_order_amount(code.get("amount"))) is not None
            and amount > 0
        )
        if total > 0:
            return round(total, 2)

    return 0.0


def summarize_discounted_order(order):
    shipments = []
    for key in ("shipments", "shipment", "shipment_details", "shipments_details"):
        value = order.get(key)
        if isinstance(value, list):
            shipments.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            shipments.append(value)

    shipment = shipments[0] if shipments else {}
    return {
        "order_id": order.get("id") or order.get("order_id"),
        "awb": next(
            (source.get(key) for source in (shipment, order)
             for key in ("awb_code", "awb", "awb_number") if source.get(key)),
            None,
        ),
        "delivery_status": order.get("status"),
        "discount": get_order_discount(order),
        "partial_cod_collected": get_partial_cod_collected(order),
        "shipping_amount": get_order_shipping_amount(order, shipments),
    }


def get_partial_cod_collected(order):
    others = order.get("others") if isinstance(order.get("others"), dict) else {}
    value = order.get("partial_cod_collected")
    if value in (None, ""):
        value = others.get("partial_cod_collected")
    return parse_order_amount(value)


def get_order_shipping_amount(order, shipments):
    others = order.get("others") if isinstance(order.get("others"), dict) else {}
    for source in (order, others, *shipments):
        for key in (
            "shipping_amount",
            "shipping_charges",
            "shipping_charge",
            "shipping_cost",
            "shipping_price",
        ):
            amount = parse_order_amount(source.get(key))
            if amount is not None:
                return amount

    shipping_lines = order.get("shipping_lines") or others.get("shipping_lines")
    if isinstance(shipping_lines, list) and shipping_lines:
        total = 0.0
        found = False
        for line in shipping_lines:
            if not isinstance(line, dict):
                continue
            price_set = line.get("discounted_price_set") or line.get("price_set") or {}
            shop_money = price_set.get("shop_money", {}) if isinstance(price_set, dict) else {}
            value = (
                shop_money.get("amount")
                if isinstance(shop_money, dict)
                else None
            )
            if value in (None, ""):
                value = line.get("discounted_price", line.get("price"))
            amount = parse_order_amount(value)
            if amount is not None:
                total += amount
                found = True
        if found:
            return round(total, 2)

    # Shiprocket's order payload may omit the shipping line amount. In that
    # case derive it from the order total and net subtotal, accounting for tax
    # only when the order total does not already include it.
    total_amount = parse_order_amount(order.get("total") or order.get("total_price"))
    subtotal_amount = parse_order_amount(
        others.get("subtotal_price") or order.get("subtotal_price")
    )
    if total_amount is None or subtotal_amount is None:
        return None

    shipping_amount = total_amount - subtotal_amount
    if others.get("taxes_included", order.get("taxes_included")) is False:
        tax_amount = parse_order_amount(order.get("tax") or others.get("total_tax")) or 0
        shipping_amount -= tax_amount
    return round(shipping_amount, 2)


def parse_order_amount(value):
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


@app.get("/api/serviceability")
def get_serviceability_date(
    pickup_postcode: str = Query(...),
    delivery_postcode: str = Query(...),
    weight: float = Query(..., ge=0.5),
    cod: int = Query(..., ge=0, le=1),
    mode: str = Query("Surface"),
):
    normalized_mode = mode.strip().capitalize()
    if normalized_mode not in {"Surface", "Air"}:
        raise HTTPException(
            status_code=400,
            detail="mode must be either Surface or Air.",
        )

    logger.info(
        "serviceability_request pickup_postcode=%s delivery_postcode=%s weight=%s cod=%s mode=%s",
        pickup_postcode,
        delivery_postcode,
        weight,
        cod,
        normalized_mode,
    )
    try:
        response_data = get_shiprocket_client().fetch_serviceability(
            pickup_postcode=pickup_postcode,
            delivery_postcode=delivery_postcode,
            weight=weight,
            cod=cod,
            mode=normalized_mode,
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


async def _receive_shopify_order_webhook(request: Request, expected_topic: str):
    secret = os.getenv("SHOPIFY_CLIENT_SECRET")
    if not secret:
        logger.error("shopify_webhook_rejected reason=secret_not_configured")
        raise HTTPException(
            status_code=503,
            detail="Shopify webhook verification is not configured.",
        )

    raw_body = await request.body()
    hmac_header = request.headers.get("x-shopify-hmac-sha256", "")
    if not hmac_header or not verify_shopify_webhook_hmac(raw_body, hmac_header, secret):
        logger.warning("shopify_webhook_rejected reason=invalid_hmac")
        raise HTTPException(status_code=401, detail="Invalid Shopify HMAC.")

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from error

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object payload.")

    topic = request.headers.get("x-shopify-topic")
    shop_domain = request.headers.get("x-shopify-shop-domain")
    webhook_id = request.headers.get("x-shopify-webhook-id")
    api_version = request.headers.get("x-shopify-api-version")
    if not webhook_id:
        raise HTTPException(status_code=400, detail="Missing Shopify webhook delivery ID.")
    expected_topic_header = expected_topic.upper()
    if not topic or topic.upper() != expected_topic_header:
        raise HTTPException(status_code=400, detail="Unexpected Shopify webhook topic.")
    test_event_code = request.headers.get("x-meta-test-event-code")
    if test_event_code:
        configured_test_code = os.getenv("META_CAPI_TEST_EVENT_CODE", "")
        if not configured_test_code or not hmac.compare_digest(
            test_event_code, configured_test_code
        ):
            raise HTTPException(
                status_code=403,
                detail="Meta test event code is not enabled for this request.",
            )
    order_summary = summarize_shopify_order_payload(payload)

    try:
        result = await run_in_threadpool(
            process_shopify_webhook,
            webhook_id=webhook_id,
            topic=topic,
            shop_domain=shop_domain,
            payload=payload,
            test_event_code=test_event_code,
        )
    except MetaDeliveryError as error:
        logger.warning(
            "shopify_meta_purchase_retry order_id=%s webhook_id=%s reason=%s",
            payload.get("id"),
            webhook_id,
            error,
        )
        raise HTTPException(
            status_code=503,
            detail="Purchase event could not be delivered; Shopify should retry.",
        ) from error
    except Exception as error:
        logger.exception(
            "shopify_webhook_processing_failed webhook_id=%s", webhook_id
        )
        raise HTTPException(
            status_code=503,
            detail="Unable to safely process Shopify webhook.",
        ) from error

    logger.info(
        "shopify_order_webhook_received topic=%s shop_domain=%s "
        "webhook_id=%s api_version=%s meta_status=%s order_summary=%s",
        topic,
        shop_domain,
        webhook_id,
        api_version,
        result["meta_status"],
        json.dumps(order_summary, ensure_ascii=True),
    )

    return {
        "ok": True,
        "message": f"Shopify {expected_topic} webhook processed.",
        "duplicate": result.get("duplicate", False),
        "meta_status": result["meta_status"],
        "meta_events_received": result.get("meta_events_received"),
        "meta_test_mode": result.get("meta_test_mode", False),
        "topic": topic,
        "shop_domain": shop_domain,
        "webhook_id": webhook_id,
        "order": order_summary,
    }


@app.post(
    "/webhooks/shopify/orders-create",
    summary="Receive Shopify Orders Create Webhook",
)
async def receive_shopify_orders_create_webhook(request: Request):
    return await _receive_shopify_order_webhook(request, "orders/create")


@app.post(
    "/webhooks/shopify/orders-paid",
    summary="Receive Shopify Orders Paid Webhook",
)
async def receive_shopify_orders_paid_webhook(request: Request):
    return await _receive_shopify_order_webhook(request, "orders/paid")


@app.post(
    "/api/meta/browser-attribution",
    summary="Save Meta Browser Attribution For A Shopify Cart",
)
async def save_browser_attribution(request: Request):
    try:
        body = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from error

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    cart_token = body.get("cart_token")
    if not isinstance(cart_token, str) or not cart_token.strip() or len(cart_token) > 2048:
        raise HTTPException(status_code=400, detail="Invalid cart token.")
    fbc, fbp = body.get("fbc"), body.get("fbp")
    if fbc is not None and not isinstance(fbc, str):
        raise HTTPException(status_code=400, detail="Invalid fbc value.")
    if fbp is not None and not isinstance(fbp, str):
        raise HTTPException(status_code=400, detail="Invalid fbp value.")

    try:
        result = await run_in_threadpool(save_meta_attribution, cart_token, fbc, fbp)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("browser_attribution_save_failed")
        raise HTTPException(status_code=503, detail="Attribution is temporarily unavailable.") from error

    return JSONResponse(
        content={"ok": True, **result},
        headers={"Cache-Control": "no-store, private"},
    )


@app.post(
    "/api/meta/browser-purchase-lookup",
    summary="Look Up Purchase Data For The Customer Account Pixel",
)
async def lookup_browser_purchase(request: Request):
    try:
        body = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from error

    order_token = body.get("order_token") if isinstance(body, dict) else None
    if (
        not isinstance(order_token, str)
        or len(order_token) != 32
        or any(character not in "0123456789abcdefABCDEF" for character in order_token)
    ):
        raise HTTPException(status_code=400, detail="Invalid order token.")

    try:
        purchase_data = await run_in_threadpool(
            get_browser_purchase_data,
            order_token,
        )
    except ValueError as error:
        logger.error("browser_purchase_lookup_invalid_record reason=%s", error)
        raise HTTPException(
            status_code=503,
            detail="Purchase data is temporarily unavailable.",
        ) from error
    except Exception as error:
        logger.exception("browser_purchase_lookup_failed")
        raise HTTPException(
            status_code=503,
            detail="Purchase data is temporarily unavailable.",
        ) from error

    if purchase_data is None:
        # Do not reveal whether a token exists for an order that wasn't delivered to Meta.
        raise HTTPException(status_code=404, detail="Purchase data not found.")

    return JSONResponse(
        content=purchase_data,
        headers={"Cache-Control": "no-store, private"},
    )


@app.get("/api/shipments/status-summary", summary="Get Shipment Status Summary By SKU")
async def get_shipment_status_summary(
    background_tasks: BackgroundTasks,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
):
    if from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from date must be less than or equal to to date.",
        )

    settings = get_edd_job_settings()
    configured_skus = parse_shipment_status_summary_skus(
        settings.shipment_status_summary_skus
    )
    if not configured_skus:
        raise HTTPException(
            status_code=503,
            detail="SHIPMENT_STATUS_SUMMARY_SKUS must contain name:channel_sku entries",
        )
    logger.info(
        "shipment_status_summary_request from=%s to=%s sku_count=%s per_page=%s",
        from_date,
        to_date,
        len(configured_skus),
        settings.per_page,
    )

    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is required to track background jobs")

    job_id = str(uuid4())
    try:
        supabase.insert("shipment_status_summary_job_runs", {
            "id": job_id,
            "status": "queued",
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "channel_sku": None,
            "per_page": settings.per_page,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as error:
        logger.exception("shipment_status_summary_queue_failed")
        raise HTTPException(status_code=502, detail=f"Unable to queue status summary job: {error}") from error

    background_tasks.add_task(
        run_shipment_status_summary_in_background,
        job_id,
        from_date.isoformat(),
        to_date.isoformat(),
        settings.per_page,
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/api/shipments/status-summary/runs/{job_id}",
        },
    )


@app.get(
    "/api/shipments/status-summary/runs/{job_id}",
    summary="Get Shipment Status Summary Job Status",
)
def get_shipment_status_summary_job_status(job_id: str):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = supabase.get("shipment_status_summary_job_runs", {"id": f"eq.{job_id}"})
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Unable to read job status: {error}") from error
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    return rows[0]


def run_shipment_status_summary_in_background(
    job_id: str,
    from_date_value: str,
    to_date_value: str,
    per_page: int,
):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    try:
        supabase.update(
            "shipment_status_summary_job_runs",
            {"id": f"eq.{job_id}"},
            {"status": "running"},
        )
        orders = get_shiprocket_client().fetch_orders(
            start_date=date.fromisoformat(from_date_value),
            end_date=date.fromisoformat(to_date_value),
            max_pages=None,
            per_page=per_page,
        )
        configured_skus = parse_shipment_status_summary_skus(
            settings.shipment_status_summary_skus
        )
        sku_summaries = []
        for sku_name, channel_skus in group_shipment_status_summary_skus(configured_skus).items():
            summary, matched_packets, ignored_statuses, rto_statuses = summarize_packets_by_status(
                orders, channel_skus
            )
            sku_summaries.append({
                "name": sku_name,
                "packets": summary,
                "rto_statuses": rto_statuses,
                "matched_packets": matched_packets,
                "ignored_packets": sum(ignored_statuses.values()),
                "ignored_statuses": ignored_statuses,
            })
        result = {
            "from": from_date_value,
            "to": to_date_value,
            "fetched_orders": len(orders),
            "sku_summaries": sku_summaries,
            "status_keywords": SHIPMENT_STATUS_BUCKETS,
        }
        supabase.update(
            "shipment_status_summary_job_runs",
            {"id": f"eq.{job_id}"},
            {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "fetched_orders": len(orders),
                "result": result,
            },
        )
        try:
            email_sent = send_shipment_status_summary_email(settings, job_id, result)
            logger.info(
                "shipment_status_summary_email_completed job_id=%s sent=%s",
                job_id,
                email_sent,
            )
        except Exception:
            logger.exception("shipment_status_summary_email_failed job_id=%s", job_id)
    except Exception as error:
        logger.exception("shipment_status_summary_job_failed job_id=%s", job_id)
        try:
            supabase.update(
                "shipment_status_summary_job_runs",
                {"id": f"eq.{job_id}"},
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error_message": str(error),
                },
            )
        except Exception:
            logger.exception("shipment_status_summary_job_status_update_failed job_id=%s", job_id)


@app.get(
    "/api/orders/discounted",
    summary="List Orders With Positive Discounts",
)
async def get_discounted_orders(
    background_tasks: BackgroundTasks,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    per_page: int = Query(100, ge=1, le=100),
):
    if from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from date must be less than or equal to to date.",
        )

    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is required to track background jobs")

    job_id = str(uuid4())
    try:
        supabase.insert("discounted_orders_job_runs", {
            "id": job_id,
            "status": "queued",
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "per_page": per_page,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as error:
        logger.exception("discounted_orders_queue_failed")
        raise HTTPException(status_code=502, detail=f"Unable to queue discounted orders job: {error}") from error

    background_tasks.add_task(
        run_discounted_orders_in_background,
        job_id,
        from_date.isoformat(),
        to_date.isoformat(),
        per_page,
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/api/orders/discounted/runs/{job_id}",
        },
    )


@app.get(
    "/api/orders/discounted/runs/{job_id}",
    summary="Get Discounted Orders Job Status",
)
def get_discounted_orders_job_status(job_id: str):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = supabase.get("discounted_orders_job_runs", {"id": f"eq.{job_id}"})
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Unable to read job status: {error}") from error
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    return rows[0]


def run_discounted_orders_in_background(
    job_id: str,
    from_date_value: str,
    to_date_value: str,
    per_page: int,
):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    try:
        supabase.update(
            "discounted_orders_job_runs",
            {"id": f"eq.{job_id}"},
            {"status": "running"},
        )
        orders = get_shiprocket_client().fetch_orders(
            start_date=date.fromisoformat(from_date_value),
            end_date=date.fromisoformat(to_date_value),
            max_pages=None,
            per_page=per_page,
        )
        discounted_orders = [
            summarize_discounted_order(order)
            for order in orders
            if isinstance(order, dict) and get_order_discount(order) > 0
        ]
        result = {
            "from": from_date_value,
            "to": to_date_value,
            "discounted_orders_count": len(discounted_orders),
            "orders": discounted_orders,
        }
        supabase.update(
            "discounted_orders_job_runs",
            {"id": f"eq.{job_id}"},
            {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "fetched_orders": len(orders),
                "discounted_orders_count": len(discounted_orders),
                "result": result,
            },
        )
    except Exception as error:
        logger.exception("discounted_orders_job_failed job_id=%s", job_id)
        try:
            supabase.update(
                "discounted_orders_job_runs",
                {"id": f"eq.{job_id}"},
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error_message": str(error),
                },
            )
        except Exception:
            logger.exception("discounted_orders_job_status_update_failed job_id=%s", job_id)


@app.get("/api/jobs/edd-breach/run", include_in_schema=False)
async def run_shipment_edd_breach_job(
    dry_run: bool = Query(False),
):
    return await execute_shipment_edd_breach_job(dry_run)


@app.get("/api/jobs/data-retention/run", include_in_schema=False)
def run_data_retention():
    try:
        return run_data_retention_job()
    except Exception as error:
        logger.exception("data_retention_job_failed")
        raise HTTPException(status_code=502, detail=f"Data retention job failed: {error}") from error


@app.post("/api/shipments/edd-breaches/run", summary="Run Shipment EDD Breach Job")
async def run_shipment_edd_breach_job_endpoint(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(False),
):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is required to track background jobs")
    job_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.insert("shipment_edd_job_runs", {
            "id": job_id,
            "job_name": "shipment_edd_breach",
            "status": "queued",
            "started_at": now,
            "dry_run": dry_run,
        })
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Unable to queue job: {error}") from error
    background_tasks.add_task(run_edd_breach_job_in_background, job_id, dry_run)
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/api/shipments/edd-breaches/runs/{job_id}",
        },
    )


@app.get("/api/shipments/edd-breaches/runs/{job_id}", summary="Get EDD Breach Job Status")
def get_shipment_edd_breach_job_status(job_id: str):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = supabase.get("shipment_edd_job_runs", {"id": f"eq.{job_id}"})
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Unable to read job status: {error}") from error
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    return rows[0]


@app.post(
    "/api/shipments/movement-concerns/run",
    summary="Run Shipment Movement Concern Job",
)
async def run_shipment_movement_concern_job_endpoint(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(False),
    awb_only: bool = Query(False),
):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is required to track background jobs")
    job_id = str(uuid4())
    try:
        supabase.insert("shipment_movement_concern_job_runs", {
            "id": job_id,
            "status": "queued",
            "dry_run": dry_run,
            "awb_only": awb_only,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Unable to queue job: {error}") from error
    background_tasks.add_task(
        run_movement_concern_job_in_background, job_id, dry_run, awb_only
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/api/shipments/movement-concerns/runs/{job_id}",
        },
    )


@app.get(
    "/api/shipments/movement-concerns/runs/{job_id}",
    summary="Get Shipment Movement Concern Job Status",
)
def get_shipment_movement_concern_job_status(job_id: str):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    if not supabase.enabled:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = supabase.get("shipment_movement_concern_job_runs", {"id": f"eq.{job_id}"})
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found")
        result = rows[0]
        if result.get("status") == "completed" and not result.get("awb_only"):
            concerns = supabase.get(
                "shipment_movement_concerns",
                {"job_run_id": f"eq.{job_id}"},
                select="awb_code,severity,reasons,edd,days_until_edd,days_since_last_movement,last_movement_date,shiprocket_order_id,channel_order_id,shipment_id,courier_name,status",
            )
            result["movement_concerns"] = concerns
        return result
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Unable to read job status: {error}") from error


def run_movement_concern_job_in_background(job_id: str, dry_run: bool, awb_only: bool):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    try:
        supabase.update(
            "shipment_movement_concern_job_runs",
            {"id": f"eq.{job_id}"},
            {"status": "running"},
        )
        run_shipment_movement_concern_job(
            dry_run=dry_run, awb_only=awb_only, job_run_id=job_id
        )
    except Exception as error:
        logger.exception("movement_concern_background_job_failed job_id=%s", job_id)
        try:
            supabase.update(
                "shipment_movement_concern_job_runs",
                {"id": f"eq.{job_id}"},
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error_message": str(error),
                },
            )
        except Exception:
            logger.exception("movement_concern_job_status_update_failed job_id=%s", job_id)


def run_edd_breach_job_in_background(job_id: str, dry_run: bool):
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    try:
        supabase.update("shipment_edd_job_runs", {"id": f"eq.{job_id}"}, {"status": "running"})
        run_edd_breach_job(dry_run=dry_run, job_run_id=job_id)
    except Exception as error:
        logger.exception("edd_breach_background_job_failed job_id=%s", job_id)
        try:
            supabase.update(
                "shipment_edd_job_runs",
                {"id": f"eq.{job_id}"},
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error_message": str(error),
                },
            )
        except Exception:
            logger.exception("edd_breach_background_job_status_update_failed job_id=%s", job_id)


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


async def execute_shipment_movement_concern_job(
    dry_run: bool,
    awb_only: bool,
):
    logger.info(
        "shipment_movement_concern_endpoint_called dry_run=%s awb_only=%s",
        dry_run,
        awb_only,
    )
    try:
        result = await run_in_threadpool(
            run_shipment_movement_concern_job,
            dry_run=dry_run,
            awb_only=awb_only,
        )
        logger.info(
            "shipment_movement_concern_endpoint_completed dry_run=%s "
            "awb_only=%s movement_concerns_found=%s",
            dry_run,
            awb_only,
            result.get("movement_concerns_found"),
        )
        logger.info(
            "shipment_movement_concern_endpoint_response=%s",
            json.dumps(result, default=str, ensure_ascii=True),
        )
        return result
    except Exception as error:
        logger.exception(
            "shipment_movement_concern_endpoint_failed dry_run=%s awb_only=%s",
            dry_run,
            awb_only,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Shipment movement concern job failed: {error}",
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

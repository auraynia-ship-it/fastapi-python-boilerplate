"""Reliable Shopify order ingestion and Meta Purchase delivery helpers."""

import hashlib
import ipaddress
import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import parse_qs, urlsplit


logger = logging.getLogger(__name__)
META_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v26.0")
META_TIMEOUT_SECONDS = 8


class MetaDeliveryError(RuntimeError):
    """A retryable Meta delivery or configuration failure."""


def _database_url():
    return (
        os.getenv("POSTGRES_URL_NON_POOLING")
        or os.getenv("POSTGRES_URL")
        or os.getenv("POSTGRES_PRISMA_URL")
    )


def _normalized(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _hashed(value):
    normalized = _normalized(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def _hash_name(value):
    value = _normalized(value)
    value = "".join(
        char for char in value
        if unicodedata.category(char)[0] in {"L", "N"}
    )
    return _hashed(value)


def _phone_digits(value, country_code):
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    if str(value).strip().startswith("+"):
        return digits
    if country_code == "IN" and len(digits) == 10:
        return "91" + digits
    if digits.startswith("00"):
        return digits[2:]
    return digits


def _order_address(order):
    return order.get("billing_address") or order.get("shipping_address") or {}


def _order_user_data(order):
    customer = order.get("customer") or {}
    address = _order_address(order)
    country = address.get("country_code") or address.get("country")
    country_iso = str(country or "").strip().upper()
    if len(country_iso) != 2:
        country_iso = ""

    user_data = {}
    email = order.get("email") or order.get("contact_email") or customer.get("email")
    if email:
        user_data["em"] = [_hashed(email)]

    phone = order.get("phone") or address.get("phone") or customer.get("phone")
    phone_value = _phone_digits(phone, country_iso)
    if phone_value:
        user_data["ph"] = [_hashed(phone_value)]

    first_name = address.get("first_name") or customer.get("first_name")
    last_name = address.get("last_name") or customer.get("last_name")
    if first_name:
        user_data["fn"] = [_hash_name(first_name)]
    if last_name:
        user_data["ln"] = [_hash_name(last_name)]

    for meta_key, address_key in (
        ("ct", "city"),
        ("st", "province_code"),
        ("zp", "zip"),
    ):
        value = address.get(address_key)
        if value:
            user_data[meta_key] = [_hashed(value)]
    if country_iso:
        user_data["country"] = [_hashed(country_iso)]

    customer_id = customer.get("id")
    if customer_id:
        # Meta's Events Manager marks External ID as an unhashed identifier.
        user_data["external_id"] = [str(customer_id)]

    note_attributes = {
        str(attribute.get("name") or "").strip().casefold(): attribute.get("value")
        for attribute in order.get("note_attributes") or []
        if isinstance(attribute, dict)
    }
    client_details = order.get("client_details") or {}
    client_ip = (
        order.get("browser_ip")
        or client_details.get("browser_ip")
        or note_attributes.get("ipv4_address")
    )
    user_agent = client_details.get("user_agent") or note_attributes.get("user_agent")
    if client_ip:
        try:
            user_data["client_ip_address"] = str(ipaddress.ip_address(str(client_ip)))
        except ValueError:
            logger.info("meta_customer_match_field_ignored name=client_ip_address")
    if user_agent:
        user_data["client_user_agent"] = str(user_agent)

    # Meta click/browser identifiers belong in user_data as fbc/fbp, not in
    # custom_data. Prefer the storefront-captured values joined by cart token.
    fbc = _valid_meta_cookie(order.get("_meta_fbc"), "fbc")
    if not fbc:
        fbc = _fbc_from_landing_url(order)
    fbp = _valid_meta_cookie(order.get("_meta_fbp"), "fbp")
    if fbc:
        user_data["fbc"] = fbc
    if fbp:
        user_data["fbp"] = fbp

    if not any(key in user_data for key in ("em", "ph", "external_id")):
        raise ValueError("Order has no usable Meta customer matching identifier.")
    return user_data


def _fbc_from_landing_url(order):
    """Build fbc from Shopify/Fastrr's preserved landing URL when available."""
    landing_url = None
    for attribute in order.get("note_attributes") or []:
        if (
            isinstance(attribute, dict)
            and str(attribute.get("name") or "").strip().casefold() == "landing_page_url"
        ):
            landing_url = attribute.get("value")
            break
    if not landing_url:
        return None
    try:
        fbclid = parse_qs(urlsplit(str(landing_url)).query).get("fbclid", [None])[0]
    except (TypeError, ValueError):
        return None
    if not isinstance(fbclid, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,500}", fbclid):
        return None

    # The original click timestamp is not included in the Shopify order payload.
    # Use order creation time as the closest available timestamp. A captured _fbc
    # from the storefront attribution endpoint takes precedence above.
    created_at = order.get("created_at") or order.get("processed_at")
    if not created_at:
        return None
    try:
        clicked_near = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if clicked_near.tzinfo is None:
            clicked_near = clicked_near.replace(tzinfo=timezone.utc)
        timestamp_ms = int(clicked_near.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None
    fbc = f"fb.1.{timestamp_ms}.{fbclid}"
    logger.info("meta_click_id_fallback source=landing_page_url")
    return fbc


def _valid_meta_cookie(value, name):
    if not isinstance(value, str) or len(value) > 500:
        return None
    # Cookie format: fb.1.<timestamp_ms>.<browser/click identifier>
    if re.fullmatch(r"fb\.1\.\d{10,16}\.[A-Za-z0-9._-]+", value):
        return value
    logger.info("meta_attribution_cookie_ignored name=%s reason=invalid_format", name)
    return None


def _cart_token_from_order(order):
    for attribute in order.get("note_attributes") or []:
        if not isinstance(attribute, dict):
            continue
        if str(attribute.get("name") or "").strip().casefold() == "shopifycarttoken":
            value = attribute.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return order.get("cart_token")


def _canonical_cart_token(value):
    """Normalize Shopify cart IDs and Fastrr cart-token note attributes."""
    if not isinstance(value, str):
        return ""
    token = value.strip().split("?", 1)[0].rstrip("/")
    if "/" in token:
        token = token.rsplit("/", 1)[-1]
    return token.strip()


def _cart_token_hash(value):
    canonical = _canonical_cart_token(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical else ""


def _order_attribution_hash(shop_domain, order_id):
    if order_id is None:
        return ""
    key = f"order:{str(shop_domain or '').strip().lower()}:{str(order_id).strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def save_meta_attribution(cart_token, fbc=None, fbp=None):
    """Store Meta click/browser IDs against a hash of Shopify's cart token."""
    database_url = _database_url()
    if not database_url:
        raise RuntimeError("Postgres connection is not configured.")
    cart_hash = _cart_token_hash(cart_token)
    fbc = _valid_meta_cookie(fbc, "fbc")
    fbp = _valid_meta_cookie(fbp, "fbp")
    if not cart_hash or not (fbc or fbp):
        raise ValueError("A cart token and valid Meta browser identifier are required.")
    import psycopg

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.shopify_meta_attribution
                    (attribution_key_hash, key_type, fbc, fbp, updated_at, expires_at)
                VALUES (%s, %s, %s, %s, now(), now() + interval '90 days')
                ON CONFLICT (attribution_key_hash) DO UPDATE SET
                    fbc = COALESCE(EXCLUDED.fbc, shopify_meta_attribution.fbc),
                    fbp = COALESCE(EXCLUDED.fbp, shopify_meta_attribution.fbp),
                    updated_at = now(),
                    expires_at = now() + interval '90 days'
                """,
                (cart_hash, "cart", fbc, fbp),
            )
    return {"stored_fbc": bool(fbc), "stored_fbp": bool(fbp)}


def _attach_meta_attribution(cursor, order, shop_domain=None):
    cart_token = _cart_token_from_order(order)
    cart_hash = _cart_token_hash(cart_token)
    cursor.execute(
        """SELECT to_regclass('public.shopify_meta_attribution') IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'shopify_meta_attribution'
                      AND column_name = 'attribution_key_hash'
                  )"""
    )
    if not cursor.fetchone()[0]:
        logger.info("meta_attribution_lookup result=table_schema_not_ready")
        return
    if cart_hash:
        cursor.execute(
            """SELECT fbc, fbp FROM public.shopify_meta_attribution
               WHERE attribution_key_hash = %s AND key_type = 'cart'
                 AND expires_at > now()""",
            (cart_hash,),
        )
        row = cursor.fetchone()
        if row:
            order["_meta_fbc"], order["_meta_fbp"] = row
            logger.info(
                "meta_attribution_lookup result=cart_match fbc_present=%s fbp_present=%s",
                bool(row[0]), bool(row[1]),
            )
            return

    order_id = order.get("id")
    if order_id is None:
        logger.info("meta_attribution_lookup result=no_order_key")
        return
    cursor.execute(
        """SELECT fbc, fbp FROM public.shopify_meta_attribution
           WHERE shop_domain IS NOT DISTINCT FROM %s AND order_id = %s
             AND key_type = 'order' AND expires_at > now()
           ORDER BY updated_at DESC LIMIT 1""",
        (shop_domain, str(order_id)),
    )
    row = cursor.fetchone()
    if row:
        order["_meta_fbc"], order["_meta_fbp"] = row
        logger.info(
            "meta_attribution_lookup result=order_match fbc_present=%s fbp_present=%s",
            bool(row[0]),
            bool(row[1]),
        )
    else:
        logger.info("meta_attribution_lookup result=no_match cart_token_present=%s", bool(cart_hash))


def _persist_order_meta_attribution(cursor, order, shop_domain=None):
    """Save click/browser IDs from this order under its stable order key."""
    cursor.execute(
        """SELECT to_regclass('public.shopify_meta_attribution') IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'shopify_meta_attribution'
                      AND column_name = 'attribution_key_hash'
                  )"""
    )
    if not cursor.fetchone()[0]:
        return
    order_id = order.get("id")
    key_hash = _order_attribution_hash(shop_domain, order_id)
    if not key_hash:
        return
    fbc = _valid_meta_cookie(order.get("_meta_fbc"), "fbc")
    if not fbc:
        fbc = _fbc_from_landing_url(order)
    fbp = _valid_meta_cookie(order.get("_meta_fbp"), "fbp")
    if not (fbc or fbp):
        return
    cursor.execute(
        """INSERT INTO public.shopify_meta_attribution
               (attribution_key_hash, key_type, shop_domain, order_id,
                fbc, fbp, updated_at, expires_at)
           VALUES (%s, 'order', %s, %s, %s, %s, now(), now() + interval '90 days')
           ON CONFLICT (attribution_key_hash) DO UPDATE SET
               fbc = COALESCE(EXCLUDED.fbc, shopify_meta_attribution.fbc),
               fbp = COALESCE(EXCLUDED.fbp, shopify_meta_attribution.fbp),
               updated_at = now(), expires_at = now() + interval '90 days'""",
        (key_hash, shop_domain, str(order_id), fbc, fbp),
    )
    logger.info(
        "meta_attribution_saved key_type=order fbc_present=%s fbp_present=%s",
        bool(fbc), bool(fbp),
    )


def _source_url(order):
    for attribute in order.get("note_attributes") or []:
        if not isinstance(attribute, dict):
            continue
        if attribute.get("name") == "landing_page_url" and attribute.get("value"):
            candidate = str(attribute["value"]).strip()
            if urlsplit(candidate).scheme == "https":
                return candidate

    candidate = os.getenv("META_EVENT_SOURCE_URL", "https://auraynia.com/").strip()
    if urlsplit(candidate).scheme != "https":
        raise ValueError("META_EVENT_SOURCE_URL must be an HTTPS URL.")
    return candidate


def _classify_payment(order):
    gateways = order.get("payment_gateway_names") or []
    if isinstance(gateways, str):
        gateways = [gateways]
    normalized = [str(value).strip().casefold() for value in gateways]
    if any("cod" in value or "cash on delivery" in value for value in normalized):
        return "COD"

    configured = os.getenv("META_PREPAID_GATEWAYS", "PayU,Razorpay")
    prepaid_gateways = {
        value.strip().casefold()
        for value in configured.split(",")
        if value.strip()
    }
    if any(
        gateway in prepaid_gateways
        or any(name in gateway for name in prepaid_gateways)
        for gateway in normalized
    ):
        return "PREPAID"
    return None


def _event_time(order):
    created_at = order.get("created_at") or order.get("processed_at")
    if not created_at:
        raise ValueError("Order is missing created_at.")
    timestamp = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    if (datetime.now(timezone.utc) - timestamp).total_seconds() > 7 * 24 * 60 * 60:
        raise LookupError("Order event is older than Meta's seven-day limit.")
    if timestamp.timestamp() > datetime.now(timezone.utc).timestamp() + 300:
        raise ValueError("Order event timestamp is unexpectedly in the future.")
    return int(timestamp.timestamp())


def _purchase_value(order, payment_type):
    try:
        total = Decimal(str(order.get("total_price")))
    except (InvalidOperation, TypeError):
        raise ValueError("Order total_price is missing or invalid.")
    if not total.is_finite() or total < 0:
        raise ValueError("Order total_price must be a non-negative amount.")
    value = total * (Decimal("0.60") if payment_type == "COD" else Decimal("1.00"))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _purchase_custom_data(order, payment_type):
    """Build the Purchase custom parameters shared by CAPI and browser lookup."""
    currency = str(order.get("currency") or "").upper()
    if not currency:
        raise ValueError("Order currency is missing.")

    line_items = order.get("line_items") or []
    contents = []
    for item in line_items:
        if not isinstance(item, dict):
            continue
        content = {
            "id": str(item.get("sku") or item.get("product_id") or item.get("variant_id") or ""),
            "quantity": item.get("quantity") or 1,
        }
        try:
            content["item_price"] = float(Decimal(str(item.get("price"))))
        except (InvalidOperation, TypeError, ValueError):
            pass
        if content["id"]:
            contents.append(content)

    custom_data = {
        "value": float(_purchase_value(order, payment_type)),
        "currency": currency,
        "order_id": str(order.get("id")),
        "content_type": "product",
        "num_items": sum(
            int(item.get("quantity") or 0)
            for item in line_items if isinstance(item, dict)
        ),
    }
    if contents:
        custom_data["contents"] = contents
        custom_data["content_ids"] = [item["id"] for item in contents]
    return custom_data


def _browser_advanced_matching_data(order):
    """Return raw values for Meta Pixel advanced matching on the order page."""
    customer = order.get("customer") or {}
    address = _order_address(order)
    country = str(address.get("country_code") or "").strip().upper()
    if len(country) != 2:
        country = ""

    values = {
        "em": order.get("email") or order.get("contact_email") or customer.get("email"),
        "ph": order.get("phone") or address.get("phone") or customer.get("phone"),
        "fn": address.get("first_name") or customer.get("first_name"),
        "ln": address.get("last_name") or customer.get("last_name"),
        "ct": address.get("city"),
        "st": address.get("province_code") or address.get("province"),
        "zp": address.get("zip"),
        "country": country,
        "external_id": customer.get("id"),
    }
    return {
        key: str(value).strip()
        for key, value in values.items()
        if value is not None and str(value).strip()
    }


def _purchase_event(order, shop_domain, payment_type):
    pixel_id = os.getenv("META_PIXEL_ID")

    event_id = f"{shop_domain or 'shop'}:{order.get('id')}:Purchase"
    event = {
        "event_name": "Purchase",
        "event_time": _event_time(order),
        "event_id": event_id,
        "action_source": "website",
        "event_source_url": _source_url(order),
        "user_data": _order_user_data(order),
        "custom_data": _purchase_custom_data(order, payment_type),
    }
    return pixel_id, event


def get_browser_purchase_data(order_token):
    """Return the minimum Purchase fields for a matching customer-account page."""
    database_url = _database_url()
    if not database_url:
        raise RuntimeError("Postgres connection is not configured.")
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("psycopg is required for webhook persistence.") from error

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT shop_domain, order_id, payload, meta_event_id, meta_value
                FROM public.shopify_webhook_events
                WHERE payload->>'token' = %s
                  AND meta_status = 'META_SENT'
                  AND status = 'PROCESSED'
                ORDER BY meta_sent_at DESC NULLS LAST
                LIMIT 2
                """,
                (order_token,),
            )
            rows = cursor.fetchall()
            if rows:
                order_payload = rows[0][2]
                if isinstance(order_payload, str):
                    order_payload = json.loads(order_payload)
                if isinstance(order_payload, dict):
                    _attach_meta_attribution(cursor, order_payload, rows[0][0])
                    _persist_order_meta_attribution(cursor, order_payload, rows[0][0])
                    rows[0] = (*rows[0][:2], order_payload, *rows[0][3:])

    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError("Order token matched multiple processed orders.")

    shop_domain, order_id, order, stored_event_id, stored_value = rows[0]
    if isinstance(order, str):
        order = json.loads(order)
    if not isinstance(order, dict) or not stored_event_id or stored_value is None:
        return None

    payment_type = _classify_payment(order)
    if payment_type is None:
        return None
    custom_data = _purchase_custom_data(order, payment_type)
    expected_event_id = f"{shop_domain or 'shop'}:{order_id}:Purchase"
    if stored_event_id != expected_event_id:
        raise ValueError("Stored Meta event ID does not match the order record.")

    # The persisted successful CAPI value is authoritative for browser deduplication.
    custom_data["value"] = float(stored_value)
    custom_data["order_id"] = str(order_id)
    fbc = _valid_meta_cookie(order.get("_meta_fbc"), "fbc") or _fbc_from_landing_url(order)
    fbp = _valid_meta_cookie(order.get("_meta_fbp"), "fbp")
    return {
        "event_id": stored_event_id,
        **custom_data,
        "advanced_matching": _browser_advanced_matching_data(order),
        "fbc": fbc,
        "fbp": fbp,
    }


def _send_to_meta(pixel_id, event, test_event_code=None):
    pixel_id = pixel_id or os.getenv("META_PIXEL_ID")
    if not pixel_id:
        raise MetaDeliveryError("META_PIXEL_ID is not configured.")
    access_token = os.getenv("META_ACCESS_TOKEN")
    if not access_token:
        raise MetaDeliveryError("META_ACCESS_TOKEN is not configured.")

    request_body = {"data": [event]}
    flag_enabled = os.getenv("META_TEST_FLAG", "").strip().casefold() == "true"
    configured_test_code = os.getenv("META_CAPI_TEST_EVENT_CODE", "").strip()
    if flag_enabled and not configured_test_code:
        raise MetaDeliveryError(
            "META_TEST_FLAG is TRUE but META_CAPI_TEST_EVENT_CODE is not configured."
        )
    effective_test_code = test_event_code or (
        configured_test_code if flag_enabled else None
    )
    if effective_test_code:
        request_body["test_event_code"] = effective_test_code

    request = urllib.request.Request(
        f"https://graph.facebook.com/{META_API_VERSION}/{pixel_id}/events",
        data=json.dumps(request_body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=META_TIMEOUT_SECONDS) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Do not persist or log the request body, which contains customer match data.
        raise MetaDeliveryError(f"Meta CAPI returned HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise MetaDeliveryError("Meta CAPI request failed or timed out.") from error

    if parsed.get("error") or parsed.get("events_received", 0) < 1:
        raise MetaDeliveryError("Meta CAPI did not accept the Purchase event.")
    return {
        "events_received": parsed.get("events_received"),
        "fbtrace_id": parsed.get("fbtrace_id"),
        "messages": parsed.get("messages", []),
        "test_mode": bool(effective_test_code),
    }


def process_shopify_webhook(
    webhook_id, topic, shop_domain, payload, test_event_code=None
):
    """Persist and process one signed Shopify event with order-level locking."""
    database_url = _database_url()
    if not database_url:
        raise RuntimeError("Postgres connection is not configured.")
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("psycopg is required for webhook persistence.") from error

    order_id = payload.get("id")
    if order_id is None:
        raise ValueError("Shopify order payload is missing id.")
    order_number = payload.get("order_number")
    topic = topic or "orders/create"
    response_result = None
    retry_error = None

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.shopify_webhook_events
                    (webhook_id, topic, shop_domain, order_id, order_number,
                     payload, status, received_at, meta_status)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'RECEIVED', now(), 'PENDING')
                ON CONFLICT (webhook_id) DO NOTHING
                """,
                (
                    webhook_id,
                    topic,
                    shop_domain,
                    str(order_id),
                    str(order_number) if order_number is not None else None,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            cursor.execute(
                """
                SELECT id, meta_status FROM public.shopify_webhook_events
                WHERE webhook_id = %s FOR UPDATE
                """,
                (webhook_id,),
            )
            row_id, meta_status = cursor.fetchone()

            # Save order-level click IDs even for a Shopify redelivery of an
            # already processed order. This must never trigger a second CAPI event.
            if payload.get("test") is not True:
                _attach_meta_attribution(cursor, payload, shop_domain)
                _persist_order_meta_attribution(cursor, payload, shop_domain)

            if meta_status in {
                "META_SENT", "SKIPPED_TEST", "SKIPPED_PAYMENT",
                "SKIPPED_CANCELLED", "SKIPPED_STALE", "SKIPPED_INVALID",
                "SKIPPED_NO_MATCH_DATA", "DUPLICATE_ORDER_PURCHASE",
            }:
                return {"meta_status": meta_status, "duplicate": True}

            order_key = f"{shop_domain or 'shop'}:{order_id}:Purchase"
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (order_key,),
            )

            if payload.get("test") is True:
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = 'SKIPPED_TEST', status = 'RECEIVED',
                           processed_at = now()
                       WHERE id = %s""",
                    (row_id,),
                )
                return {"meta_status": "SKIPPED_TEST", "duplicate": False}

            cursor.execute(
                """SELECT 1 FROM public.shopify_webhook_events
                   WHERE shop_domain IS NOT DISTINCT FROM %s
                     AND order_id = %s AND meta_status = 'META_SENT'
                   LIMIT 1""",
                (shop_domain, str(order_id)),
            )
            if cursor.fetchone():
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = 'DUPLICATE_ORDER_PURCHASE',
                           meta_event_id = %s, processed_at = now()
                       WHERE id = %s""",
                    (order_key, row_id),
                )
                return {"meta_status": "DUPLICATE_ORDER_PURCHASE", "duplicate": True}

            if payload.get("cancelled_at") or payload.get("cancel_reason"):
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = 'SKIPPED_CANCELLED', processed_at = now()
                       WHERE id = %s""",
                    (row_id,),
                )
                return {"meta_status": "SKIPPED_CANCELLED", "duplicate": False}

            payment_type = _classify_payment(payload)
            if payment_type is None:
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = 'SKIPPED_PAYMENT',
                           meta_error = 'Unrecognized payment gateway', processed_at = now()
                       WHERE id = %s""",
                    (row_id,),
                )
                return {"meta_status": "SKIPPED_PAYMENT", "duplicate": False}

            if topic.casefold() not in {"orders/create", "orders/paid"}:
                raise ValueError("Unsupported Shopify topic for Purchase processing.")

            try:
                pixel_id, event = _purchase_event(payload, shop_domain, payment_type)
            except LookupError as error:
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = 'SKIPPED_STALE', meta_error = %s,
                           processed_at = now()
                       WHERE id = %s""",
                    (str(error), row_id),
                )
                return {"meta_status": "SKIPPED_STALE", "duplicate": False}
            except MetaDeliveryError as error:
                retry_error = str(error)
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = 'RETRY', meta_error = %s, status = 'RECEIVED'
                       WHERE id = %s""",
                    (retry_error, row_id),
                )
                event = None
            except ValueError as error:
                status = (
                    "SKIPPED_NO_MATCH_DATA"
                    if "matching identifier" in str(error)
                    else "SKIPPED_INVALID"
                )
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = %s, meta_error = %s, processed_at = now()
                       WHERE id = %s""",
                    (status, str(error), row_id),
                )
                return {"meta_status": status, "duplicate": False}

            if event is not None:
                event_id = event["event_id"]
                value = event["custom_data"]["value"]
                cursor.execute(
                    """UPDATE public.shopify_webhook_events
                       SET meta_status = 'PROCESSING', meta_event_id = %s,
                           meta_value = %s, meta_error = NULL,
                           meta_attempts = meta_attempts + 1
                       WHERE id = %s""",
                    (event_id, value, row_id),
                )
                try:
                    meta_response = _send_to_meta(
                        pixel_id, event, test_event_code=test_event_code
                    )
                except MetaDeliveryError as error:
                    retry_error = str(error)
                    cursor.execute(
                        """UPDATE public.shopify_webhook_events
                           SET meta_status = 'RETRY', meta_error = %s, status = 'RECEIVED'
                           WHERE id = %s""",
                        (retry_error, row_id),
                    )
                else:
                    cursor.execute(
                        """UPDATE public.shopify_webhook_events
                           SET meta_status = 'META_SENT', meta_error = NULL,
                               meta_response = %s::jsonb, meta_sent_at = now(),
                               processed_at = now(), status = 'PROCESSED'
                           WHERE id = %s""",
                        (json.dumps(meta_response), row_id),
                    )
                    response_result = {
                        "meta_status": "META_SENT",
                        "duplicate": False,
                        "meta_events_received": meta_response.get("events_received"),
                        "meta_fbtrace_id": meta_response.get("fbtrace_id"),
                        "meta_event_id": event_id,
                        "meta_value": value,
                        "meta_currency": event["custom_data"]["currency"],
                        "meta_test_mode": meta_response.get("test_mode", False),
                    }

    if response_result and response_result["meta_status"] == "META_SENT":
        logger.info(
            "meta_purchase_accepted mode=%s order_id=%s webhook_id=%s event_id=%s "
            "value=%s currency=%s events_received=%s fbtrace_id=%s",
            "TEST" if response_result["meta_test_mode"] else "PRODUCTION",
            order_id,
            webhook_id,
            response_result["meta_event_id"],
            response_result["meta_value"],
            response_result["meta_currency"],
            response_result["meta_events_received"],
            response_result["meta_fbtrace_id"],
        )

    if retry_error:
        logger.error(
            "meta_purchase_delivery_failed order_id=%s topic=%s error=%s",
            order_id,
            topic,
            retry_error,
        )
        raise MetaDeliveryError(retry_error)
    return response_result

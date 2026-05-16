import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import get_edd_job_settings
from .shiprocket import ShiprocketClient
from .supabase import SupabaseRestClient


DATE_FIELDS = (
    "edd",
    "expected_delivery_date",
    "estimated_delivery_date",
    "etd",
    "promise_date",
)
DELIVERED_FIELDS = ("delivered_date", "delivery_date", "actual_delivery_date")
RTO_FIELDS = ("rto_initiated_date", "rto_delivered_date", "rto_date")
AWB_FIELDS = ("awb_code", "awb", "awb_number")


def run_edd_breach_job(today=None, dry_run=False):
    settings = get_edd_job_settings()
    today = today or business_today(settings.timezone)
    started_at = datetime.now(timezone.utc)

    shiprocket = ShiprocketClient(
        token=settings.shiprocket_token,
        email=settings.shiprocket_email,
        password=settings.shiprocket_password,
    )
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)

    start_date = today - timedelta(days=settings.order_window_days)
    orders = shiprocket.fetch_orders(
        start_date=start_date,
        end_date=today,
        max_pages=settings.max_pages,
        per_page=settings.per_page,
    )
    snapshots = []
    breaches = []

    for order in orders:
        for shipment in iter_shipments(order):
            snapshot = build_snapshot(order, shipment, today)
            if not snapshot.get("awb_code"):
                continue
            snapshots.append(snapshot)

            if is_edd_breached(snapshot, today):
                breaches.append(build_breach(snapshot, today))

    report_path = write_breach_csv(breaches, settings.report_dir, today)
    completed_at = datetime.now(timezone.utc)

    job_run = {
        "job_name": "shipment_edd_breach",
        "status": "completed",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "orders_fetched": len(orders),
        "shipments_checked": len(snapshots),
        "breaches_found": len(breaches),
        "report_path": str(report_path),
        "awb_codes": [breach["awb_code"] for breach in breaches],
    }

    if not dry_run:
        persisted_run = supabase.insert("shipment_edd_job_runs", job_run)
        job_run_id = persisted_run[0].get("id") if persisted_run else None

        if snapshots:
            supabase.upsert(
                "shipment_snapshots",
                snapshots,
                on_conflict="awb_code",
                returning="minimal",
            )

        if breaches:
            breach_rows = [
                {**breach, "job_run_id": job_run_id}
                for breach in breaches
            ]
            supabase.upsert(
                "shipment_edd_breaches",
                breach_rows,
                on_conflict="awb_code,breach_date",
                returning="minimal",
            )

    awb_codes = [breach["awb_code"] for breach in breaches]
    print(f"EDD breached AWBs: {', '.join(awb_codes) if awb_codes else 'none'}")

    return {
        "status": "completed",
        "dry_run": dry_run,
        "orders_fetched": len(orders),
        "shipments_checked": len(snapshots),
        "breaches_found": len(breaches),
        "breached_awbs": awb_codes,
        "report_path": str(report_path),
    }


def business_today(timezone_name):
    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tzinfo = timezone.utc
    return datetime.now(tzinfo).date()


def iter_shipments(order):
    shipment_lists = []
    for key in ("shipments", "shipment", "shipment_details", "shipments_details"):
        value = order.get(key) if isinstance(order, dict) else None
        if isinstance(value, list):
            shipment_lists.extend(value)
        elif isinstance(value, dict):
            shipment_lists.append(value)

    if shipment_lists:
        for shipment in shipment_lists:
            merged = {**order, **shipment}
            yield merged
    else:
        yield order


def build_snapshot(order, shipment, today):
    awb_code = first_value(shipment, AWB_FIELDS) or first_value(order, AWB_FIELDS)
    edd = parse_date(first_value(shipment, DATE_FIELDS) or first_value(order, DATE_FIELDS))
    delivered_date = parse_date(
        first_value(shipment, DELIVERED_FIELDS) or first_value(order, DELIVERED_FIELDS)
    )
    rto_initiated_date = parse_date(
        first_value(shipment, RTO_FIELDS) or first_value(order, RTO_FIELDS)
    )

    return {
        "awb_code": clean_value(awb_code),
        "shiprocket_order_id": clean_value(
            order.get("id") or order.get("order_id") or shipment.get("order_id")
        ),
        "channel_order_id": clean_value(
            shipment.get("channel_order_id") or order.get("channel_order_id")
        ),
        "shipment_id": clean_value(
            shipment.get("shipment_id") or shipment.get("id") or order.get("shipment_id")
        ),
        "courier_name": clean_value(
            shipment.get("courier_name")
            or shipment.get("courier_company")
            or order.get("courier_name")
        ),
        "status": clean_value(shipment.get("status") or order.get("status")),
        "edd": edd.isoformat() if edd else None,
        "delivered_date": delivered_date.isoformat() if delivered_date else None,
        "rto_initiated_date": rto_initiated_date.isoformat() if rto_initiated_date else None,
        "last_checked_date": today.isoformat(),
        "raw_payload": shipment,
    }


def build_breach(snapshot, today):
    edd = date.fromisoformat(snapshot["edd"])
    return {
        "awb_code": snapshot["awb_code"],
        "breach_date": today.isoformat(),
        "edd": snapshot["edd"],
        "days_delayed": (today - edd).days,
        "shiprocket_order_id": snapshot.get("shiprocket_order_id"),
        "channel_order_id": snapshot.get("channel_order_id"),
        "shipment_id": snapshot.get("shipment_id"),
        "courier_name": snapshot.get("courier_name"),
        "status": snapshot.get("status"),
        "delivered_date": snapshot.get("delivered_date"),
        "rto_initiated_date": snapshot.get("rto_initiated_date"),
        "raw_payload": snapshot.get("raw_payload"),
    }


def is_edd_breached(snapshot, today):
    if not snapshot.get("edd"):
        return False

    edd = date.fromisoformat(snapshot["edd"])
    return (
        today > edd
        and not snapshot.get("delivered_date")
        and not snapshot.get("rto_initiated_date")
    )


def write_breach_csv(breaches, report_dir, today):
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / f"shipment_edd_breaches_{today.isoformat()}.csv"

    fieldnames = [
        "awb_code",
        "breach_date",
        "edd",
        "days_delayed",
        "shiprocket_order_id",
        "channel_order_id",
        "shipment_id",
        "courier_name",
        "status",
        "delivered_date",
        "rto_initiated_date",
    ]
    with report_path.open("w", newline="", encoding="utf-8") as report:
        writer = csv.DictWriter(report, fieldnames=fieldnames)
        writer.writeheader()
        for breach in breaches:
            writer.writerow({key: breach.get(key) for key in fieldnames})

    return report_path


def first_value(mapping, keys):
    if not isinstance(mapping, dict):
        return None

    for key in keys:
        value = mapping.get(key)
        if has_value(value):
            return value
    return None


def has_value(value):
    return value not in (None, "", "0000-00-00", "0000-00-00 00:00:00", "null")


def clean_value(value):
    if not has_value(value):
        return None
    return str(value)


def parse_date(value):
    if not has_value(value):
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


import csv
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import get_edd_job_settings
from .blob_store import upload_bytes_to_vercel_blob
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
MOVEMENT_DATE_FIELDS = (
    "last_movement_date",
    "last_scan_date",
    "last_status_date",
    "status_date",
    "updated_at",
    "updated_on",
    "shipment_track_activities_date",
    "activity_date",
    "scan_date",
    "event_date",
    "pickup_date",
    "shipped_date",
)
CONCERN_STATUS_TERMS = (
    "delay",
    "delayed",
    "exception",
    "hold",
    "held",
    "undelivered",
    "failed",
    "lost",
    "damaged",
    "misroute",
    "misrouted",
)
OPEN_STATUS_TERMS = (
    "manifest",
    "pickup",
    "picked",
    "in transit",
    "transit",
    "shipped",
    "out for delivery",
)
FINAL_STATUS_TERMS = ("delivered", "rto", "return", "cancel")
SKIPPED_MOVEMENT_CONCERN_STATUSES = ("out for pickup", "pickup scheduled")
logger = logging.getLogger(__name__)


def run_edd_breach_job(today=None, dry_run=False):
    settings = get_edd_job_settings()
    today = today or business_today(settings.timezone)
    started_at = datetime.now(timezone.utc)
    logger.info(
        "edd_breach_job_started dry_run=%s today=%s timezone=%s order_window_days=%s "
        "shiprocket_token_present=%s shiprocket_credentials_present=%s "
        "supabase_configured=%s blob_store_configured=%s report_dir=%s",
        dry_run,
        today.isoformat(),
        settings.timezone,
        settings.order_window_days,
        bool(settings.shiprocket_token),
        bool(settings.shiprocket_email and settings.shiprocket_password),
        bool(settings.supabase_url and settings.supabase_key),
        bool(settings.blob_rw_token),
        settings.report_dir,
    )

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
    logger.info(
        "edd_breach_orders_fetched count=%s start_date=%s end_date=%s max_pages=%s per_page=%s",
        len(orders),
        start_date.isoformat(),
        today.isoformat(),
        settings.max_pages,
        settings.per_page,
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
    logger.info(
        "edd_breach_shipments_evaluated shipments_checked=%s breaches_found=%s",
        len(snapshots),
        len(breaches),
    )

    report_csv_path = write_breach_csv(breaches, settings.report_dir, today)
    report_pdf_path = write_breach_pdf(breaches, settings.report_dir, today)
    logger.info(
        "edd_breach_reports_created csv_path=%s pdf_path=%s",
        report_csv_path,
        report_pdf_path,
    )
    report_blob_url = None
    report_blob_upload = {
        "attempted": False,
        "uploaded": False,
        "skipped_reason": None,
    }
    if dry_run:
        report_blob_upload["skipped_reason"] = "dry_run_enabled"
        logger.info("edd_breach_blob_upload_skipped reason=dry_run_enabled")
    elif not report_pdf_path:
        report_blob_upload["skipped_reason"] = "pdf_report_not_created"
        logger.warning("edd_breach_blob_upload_skipped reason=pdf_report_not_created")
    elif not settings.blob_rw_token:
        report_blob_upload["skipped_reason"] = "BLOB_READ_WRITE_TOKEN is not configured"
        logger.warning("edd_breach_blob_upload_skipped reason=blob_token_missing")
    else:
        report_blob_upload["attempted"] = True
        logger.info(
            "edd_breach_blob_upload_started pdf_path=%s prefix=%s access=%s",
            report_pdf_path,
            settings.blob_prefix,
            settings.blob_access,
        )
        try:
            report_blob_url = upload_report_to_blob(
                local_path=report_pdf_path,
                today=today,
                prefix=settings.blob_prefix,
                access=settings.blob_access,
                token=settings.blob_rw_token,
            )
        except Exception:
            logger.exception("edd_breach_blob_upload_failed pdf_path=%s", report_pdf_path)
            raise
        report_blob_upload["uploaded"] = True
        report_blob_upload["url"] = report_blob_url
        logger.info("edd_breach_blob_upload_completed url=%s", report_blob_url)
    completed_at = datetime.now(timezone.utc)

    job_run = {
        "job_name": "shipment_edd_breach",
        "status": "completed",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "orders_fetched": len(orders),
        "shipments_checked": len(snapshots),
        "breaches_found": len(breaches),
        "report_path": str(report_blob_url or report_pdf_path or report_csv_path),
        "report_csv_path": str(report_csv_path) if report_csv_path else None,
        "report_pdf_path": str(report_pdf_path) if report_pdf_path else None,
        "report_blob_url": report_blob_url,
        "awb_codes": [breach["awb_code"] for breach in breaches],
    }

    if not dry_run:
        logger.info("edd_breach_persist_started")
        persisted_run = supabase.insert("shipment_edd_job_runs", job_run)
        job_run_id = persisted_run[0].get("id") if persisted_run else None
        logger.info("edd_breach_job_run_persisted job_run_id=%s", job_run_id)

        if snapshots:
            supabase.upsert(
                "shipment_snapshots",
                snapshots,
                on_conflict="awb_code",
                returning="minimal",
            )
            logger.info("edd_breach_snapshots_upserted count=%s", len(snapshots))

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
            logger.info("edd_breach_rows_upserted count=%s", len(breaches))
    else:
        logger.info("edd_breach_persist_skipped reason=dry_run_enabled")

    awb_codes = [breach["awb_code"] for breach in breaches]
    logger.info(
        "edd_breach_job_completed orders_fetched=%s shipments_checked=%s "
        "breaches_found=%s report_blob_url_present=%s breached_awbs=%s",
        len(orders),
        len(snapshots),
        len(breaches),
        bool(report_blob_url),
        ",".join(awb_codes) if awb_codes else "none",
    )

    return {
        "status": "completed",
        "dry_run": dry_run,
        "orders_fetched": len(orders),
        "shipments_checked": len(snapshots),
        "breaches_found": len(breaches),
        "breached_awbs": awb_codes,
        "report_path": str(report_blob_url or report_pdf_path or report_csv_path),
        "report_csv_path": str(report_csv_path) if report_csv_path else None,
        "report_pdf_path": str(report_pdf_path) if report_pdf_path else None,
        "report_blob_url": report_blob_url,
        "report_blob_upload": report_blob_upload,
    }


def run_shipment_movement_concern_job(today=None, dry_run=False, awb_only=False):
    settings = get_edd_job_settings()
    today = today or business_today(settings.timezone)
    logger.info(
        "shipment_movement_concern_job_started dry_run=%s awb_only=%s today=%s timezone=%s "
        "order_window_days=%s shiprocket_token_present=%s "
        "shiprocket_credentials_present=%s supabase_configured=%s report_dir=%s",
        dry_run,
        awb_only,
        today.isoformat(),
        settings.timezone,
        settings.order_window_days,
        bool(settings.shiprocket_token),
        bool(settings.shiprocket_email and settings.shiprocket_password),
        bool(settings.supabase_url and settings.supabase_key),
        settings.report_dir,
    )

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
    movement_concerns = []

    for order in orders:
        for shipment in iter_shipments(order):
            snapshot = build_snapshot(order, shipment, today)
            if not snapshot.get("awb_code"):
                continue
            snapshots.append(snapshot)
            concern = build_movement_concern(snapshot, today)
            if concern:
                movement_concerns.append(concern)

    report_csv_path = write_movement_concern_csv(
        movement_concerns,
        settings.report_dir,
        today,
    )

    if not dry_run and snapshots:
        supabase.upsert(
            "shipment_snapshots",
            snapshots,
            on_conflict="awb_code",
            returning="minimal",
        )
        logger.info("shipment_movement_concern_snapshots_upserted count=%s", len(snapshots))
    elif dry_run:
        logger.info("shipment_movement_concern_persist_skipped reason=dry_run_enabled")

    logger.info(
        "shipment_movement_concern_job_completed orders_fetched=%s "
        "shipments_checked=%s movement_concerns_found=%s",
        len(orders),
        len(snapshots),
        len(movement_concerns),
    )

    awb_codes = [concern["awb_code"] for concern in movement_concerns]
    response = {
        "status": "completed",
        "dry_run": dry_run,
        "orders_fetched": len(orders),
        "shipments_checked": len(snapshots),
        "movement_concerns_found": len(movement_concerns),
        "report_csv_path": str(report_csv_path) if report_csv_path else None,
    }
    if awb_only:
        response["awb_codes"] = awb_codes
    else:
        response["movement_concerns"] = movement_concerns

    return response


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


def build_movement_concern(snapshot, today):
    if is_shipment_closed(snapshot):
        return None

    raw_payload = snapshot.get("raw_payload") or {}
    status = snapshot.get("status") or ""
    status_text = normalize_status(status)
    if status_text in SKIPPED_MOVEMENT_CONCERN_STATUSES:
        return None

    latest_movement_date = latest_payload_date(raw_payload, MOVEMENT_DATE_FIELDS)
    days_since_movement = (
        (today - latest_movement_date).days if latest_movement_date else None
    )
    edd = date.fromisoformat(snapshot["edd"]) if snapshot.get("edd") else None
    days_until_edd = (edd - today).days if edd else None
    reasons = []
    severity = None

    if is_edd_breached(snapshot, today):
        reasons.append("EDD breached and shipment is still open")
        severity = "high"

    if any(term in status_text for term in CONCERN_STATUS_TERMS):
        reasons.append(f"status is concerning: {status}")
        severity = "high"

    if days_since_movement is None:
        if edd and days_until_edd <= 2:
            reasons.append("no movement timestamp found near EDD")
            severity = severity or "medium"
    elif days_since_movement >= 5:
        reasons.append(f"no movement for {days_since_movement} days")
        severity = "high"
    elif days_since_movement >= 3 and edd and days_until_edd <= 2:
        reasons.append(
            f"no movement for {days_since_movement} days with EDD within 2 days"
        )
        severity = severity or "medium"
    elif (
        days_since_movement >= 2
        and edd
        and days_until_edd is not None
        and days_until_edd <= 1
        and any(term in status_text for term in OPEN_STATUS_TERMS)
    ):
        reasons.append(
            f"slow movement near EDD: {days_since_movement} days since last scan"
        )
        severity = severity or "medium"

    if not reasons:
        return None

    return {
        "awb_code": snapshot["awb_code"],
        "severity": severity or "low",
        "reasons": reasons,
        "edd": snapshot.get("edd"),
        "days_until_edd": days_until_edd,
        "days_since_last_movement": days_since_movement,
        "last_movement_date": latest_movement_date.isoformat()
        if latest_movement_date
        else None,
        "shiprocket_order_id": snapshot.get("shiprocket_order_id"),
        "channel_order_id": snapshot.get("channel_order_id"),
        "shipment_id": snapshot.get("shipment_id"),
        "courier_name": snapshot.get("courier_name"),
        "status": snapshot.get("status"),
    }


def is_shipment_closed(snapshot):
    if snapshot.get("delivered_date") or snapshot.get("rto_initiated_date"):
        return True

    status = normalize_status(snapshot.get("status"))
    return any(term in status for term in FINAL_STATUS_TERMS)


def normalize_status(status):
    return " ".join(str(status or "").strip().lower().split())


def latest_payload_date(value, matching_keys):
    dates = []
    collect_payload_dates(value, {key.lower() for key in matching_keys}, dates)
    return max(dates) if dates else None


def collect_payload_dates(value, matching_keys, dates):
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).lower()
            if normalized_key in matching_keys or (
                "date" in normalized_key
                and any(term in normalized_key for term in ("scan", "status", "activity"))
            ):
                parsed_date = parse_date(nested_value)
                if parsed_date:
                    dates.append(parsed_date)
            collect_payload_dates(nested_value, matching_keys, dates)
    elif isinstance(value, list):
        for item in value:
            collect_payload_dates(item, matching_keys, dates)


def write_movement_concern_csv(movement_concerns, report_dir, today):
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / f"shipment_movement_concerns_{today.isoformat()}.csv"

    fieldnames = [
        "awb_code",
        "severity",
        "reasons",
        "edd",
        "days_until_edd",
        "days_since_last_movement",
        "last_movement_date",
        "shiprocket_order_id",
        "channel_order_id",
        "shipment_id",
        "courier_name",
        "status",
    ]
    with report_path.open("w", newline="", encoding="utf-8") as report:
        writer = csv.DictWriter(report, fieldnames=fieldnames)
        writer.writeheader()
        for concern in movement_concerns:
            row = {key: concern.get(key) for key in fieldnames}
            row["reasons"] = "; ".join(concern.get("reasons") or [])
            writer.writerow(row)

    return report_path


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


def write_breach_pdf(breaches, report_dir, today):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError:
        logger.warning("reportlab_missing_using_simple_pdf_writer")
        return write_simple_breach_pdf(breaches, report_dir, today)

    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / f"shipment_edd_breaches_{today.isoformat()}.pdf"

    c = canvas.Canvas(str(report_path), pagesize=A4)
    width, height = A4
    x = 15 * mm
    y = height - 20 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, f"Shipment EDD Breaches - {today.isoformat()}")
    y -= 10 * mm

    c.setFont("Helvetica", 9)
    headers = ["AWB", "EDD", "Days", "Courier", "Status"]
    c.drawString(x, y, " | ".join(headers))
    y -= 6 * mm

    if not breaches:
        c.drawString(x, y, "No EDD breaches found.")

    for breach in breaches:
        line = " | ".join(
            [
                str(breach.get("awb_code") or ""),
                str(breach.get("edd") or ""),
                str(breach.get("days_delayed") or ""),
                str(breach.get("courier_name") or "")[:24],
                str(breach.get("status") or "")[:18],
            ]
        )
        c.drawString(x, y, line)
        y -= 5 * mm
        if y < 15 * mm:
            c.showPage()
            y = height - 20 * mm
            c.setFont("Helvetica", 9)

    c.save()
    return report_path


def write_simple_breach_pdf(breaches, report_dir, today):
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / f"shipment_edd_breaches_{today.isoformat()}.pdf"

    lines = [f"Shipment EDD Breaches - {today.isoformat()}", ""]
    if breaches:
        lines.append("AWB | EDD | Days | Courier | Status")
        for breach in breaches:
            lines.append(
                " | ".join(
                    [
                        str(breach.get("awb_code") or ""),
                        str(breach.get("edd") or ""),
                        str(breach.get("days_delayed") or ""),
                        str(breach.get("courier_name") or "")[:24],
                        str(breach.get("status") or "")[:18],
                    ]
                )
            )
    else:
        lines.append("No EDD breaches found.")

    content_lines = ["BT", "/F1 12 Tf", "50 790 Td"]
    for index, line in enumerate(lines[:45]):
        if index:
            content_lines.append("0 -16 Td")
        content_lines.append(f"({escape_pdf_text(line)}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content
        + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_position = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_position}\n%%EOF\n"
        ).encode("ascii")
    )

    report_path.write_bytes(pdf)
    return report_path


def escape_pdf_text(text):
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def upload_report_to_blob(*, local_path, today, prefix, access, token):
    content = Path(local_path).read_bytes()
    pathname = f"{prefix}/shipment_edd_breaches_{today.isoformat()}.pdf"
    result = upload_bytes_to_vercel_blob(
        pathname=pathname,
        content=content,
        content_type="application/pdf",
        access=access,
        token=token,
    )
    return result.url


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

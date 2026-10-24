"""Email notifications for shipment status summary jobs."""

import json
import re
import logging
import smtplib
from html import escape
from email.message import EmailMessage


logger = logging.getLogger(__name__)


def _render_table(title, values):
    if not values:
        return ""
    rows = "".join(
        "<tr>"
        f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb">{escape(str(key))}</td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right">{escape(str(value))}</td>'
        "</tr>"
        for key, value in values.items()
    )
    return (
        '<h2 style="font-size:16px;margin:24px 0 8px">'
        f"{escape(title)}</h2>"
        '<table role="presentation" style="width:100%;border-collapse:collapse;'
        'background:#fff;border:1px solid #e5e7eb">'
        f"{rows}</table>"
    )


def _summary_email_bodies(job_id, result):
    status_keywords = result.get("status_keywords") or {}
    sku_summaries = result.get("sku_summaries") or []

    text_body = (
        "Shipment Status Summary\n"
        f"Date range: {result.get('from')} to {result.get('to')}\n"
        f"Fetched orders: {result.get('fetched_orders', 0)}\n"
        f"Job ID: {job_id}\n"
    )
    sku_sections = []
    for sku_summary in sku_summaries:
        packets = sku_summary.get("packets") or {}
        rto_statuses = sku_summary.get("rto_statuses") or {}
        ignored_statuses = sku_summary.get("ignored_statuses") or {}
        name = sku_summary.get("name") or "Unnamed SKU"
        text_body += (
            f"\n{name}\n"
            f"Matched packets: {sku_summary.get('matched_packets', 0)}\n"
            f"Ignored packets: {sku_summary.get('ignored_packets', 0)}\n"
            f"Packet statuses: {json.dumps(packets, indent=2, ensure_ascii=False)}\n"
            f"RTO statuses: {json.dumps(rto_statuses, indent=2, ensure_ascii=False)}\n"
            f"Ignored statuses: {json.dumps(ignored_statuses, indent=2, ensure_ascii=False)}\n"
        )
        cards = "".join(
            '<td style="width:33%;padding:12px;border:1px solid #e5e7eb;'
            'background:#fff;text-align:center">'
            f'<div style="font-size:12px;color:#6b7280">{escape(label)}</div>'
            f'<div style="font-size:24px;font-weight:700;color:#111827">{escape(str(value))}</div>'
            "</td>"
            for label, value in (
                ("Matched packets", sku_summary.get("matched_packets", 0)),
                ("Ignored packets", sku_summary.get("ignored_packets", 0)),
            )
        )
        sku_sections.append(
            '<section style="margin-top:24px">'
            f'<h2 style="font-size:18px;margin:0 0 10px">{escape(str(name))}</h2>'
            f'<table role="presentation" style="width:100%;border-collapse:collapse">{cards}</table>'
            f"{_render_table('Packet status', packets)}"
            f"{_render_table('RTO status breakdown', rto_statuses)}"
            f"{_render_table('Ignored status breakdown', ignored_statuses)}"
            "</section>"
        )
    text_body += (
        "\nStatus keywords: "
        f"{json.dumps(status_keywords, indent=2, ensure_ascii=False)}\n"
    )
    keywords = "".join(
        "<li>"
        f"<strong>{escape(str(key).replace('_', ' ').title())}:</strong> "
        f"{escape(str(value))}</li>"
        for key, value in status_keywords.items()
    )
    html_body = (
        '<div style="margin:0;background:#f3f4f6;padding:24px;font-family:Arial,sans-serif;'
        'color:#111827">'
        '<div style="max-width:680px;margin:0 auto;background:#f9fafb;padding:24px;'
        'border-radius:10px">'
        '<div style="font-size:12px;font-weight:700;letter-spacing:.08em;color:#2563eb;'
        'text-transform:uppercase">Shipment report</div>'
        '<h1 style="font-size:24px;margin:8px 0 4px">Status Summary</h1>'
        '<p style="margin:0;color:#4b5563">'
        f"{escape(str(result.get('from', '')))} to {escape(str(result.get('to', '')))}</p>"
        '<p style="margin:8px 0 20px;color:#4b5563">'
        f"<strong>Fetched orders:</strong> {escape(str(result.get('fetched_orders', 0)))}</p>"
        f"{''.join(sku_sections)}"
        '<h2 style="font-size:16px;margin:24px 0 8px">Status matching keywords</h2>'
        f'<ul style="padding-left:20px;color:#4b5563">{keywords}</ul>'
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid #d1d5db;'
        'font-size:12px;color:#6b7280">'
        f"Job ID: {escape(str(job_id))}<br>"
        f'Status URL: /api/shipments/status-summary/runs/{escape(str(job_id))}'
        "</div></div></div>"
    )
    return text_body, html_body


def send_shipment_status_summary_email(settings, job_id, result, test=False):
    """Send the completed summary to the configured recipient, if enabled."""
    recipients = [
        address.strip()
        for address in re.split(r"[,;\n]+", settings.shipment_status_summary_email_to or "")
        if address.strip()
    ]
    if not (
        settings.gmail_app_email
        and settings.gmail_app_password
        and recipients
    ):
        return False

    message = EmailMessage()
    message["Subject"] = (
        "Shipment status summary SMTP test"
        if test
        else f"Shipment status summary: {result['from']} to {result['to']}"
    )
    message["From"] = settings.gmail_app_email
    message["To"] = ", ".join(recipients)
    if test:
        text_body = (
            "This is a test email from the shipment status summary SMTP integration.\n"
            "If you received it, Gmail SMTP authentication and delivery are working.\n"
        )
        html_body = (
            '<div style="font-family:Arial,sans-serif;color:#111827;padding:24px">'
            '<h1 style="font-size:22px">Shipment summary email test</h1>'
            '<p>If you received this message, Gmail SMTP authentication and delivery are working.</p>'
            "</div>"
        )
        message.set_content(
            text_body
        )
        message.add_alternative(html_body, subtype="html")
    else:
        text_body, html_body = _summary_email_bodies(job_id, result)
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

    password = settings.gmail_app_password.replace(" ", "")
    transports = (
        ("STARTTLS", 587),
        ("SSL", 465),
    )
    smtp = None
    for index, (transport, port) in enumerate(transports):
        candidate = None
        try:
            if transport == "STARTTLS":
                candidate = smtplib.SMTP("smtp.gmail.com", port, timeout=30)
                candidate.ehlo()
                candidate.starttls()
                candidate.ehlo()
            else:
                candidate = smtplib.SMTP_SSL("smtp.gmail.com", port, timeout=30)
            candidate.login(settings.gmail_app_email, password)
            smtp = candidate
            break
        except smtplib.SMTPAuthenticationError:
            if candidate is not None:
                candidate.close()
            logger.error(
                "shipment_status_summary_smtp_auth_rejected transport=%s port=%s; "
                "verify the Gmail account, App Password, and account security settings",
                transport,
                port,
            )
            raise
        except (smtplib.SMTPServerDisconnected, OSError) as error:
            if candidate is not None:
                candidate.close()
            logger.warning(
                "shipment_status_summary_smtp_connection_failed transport=%s port=%s error_type=%s",
                transport,
                port,
                type(error).__name__,
            )
            if index == len(transports) - 1:
                raise

    try:
        smtp.send_message(message, to_addrs=recipients)
        return True
    finally:
        try:
            smtp.quit()
        except (smtplib.SMTPServerDisconnected, OSError):
            smtp.close()

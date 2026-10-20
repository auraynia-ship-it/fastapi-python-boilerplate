from app.config.settings import get_edd_job_settings


RETENTION_TABLES = (
    ("shipment_edd_breaches", "created_at"),
    ("shipment_snapshots", "created_at"),
    ("shipment_edd_job_runs", "created_at"),
    ("shopify_webhook_events", "created_at"),
    ("shopify_meta_attribution", "created_at"),
)


def run_data_retention_job():
    settings = get_edd_job_settings()
    if not settings.postgres_url:
        raise RuntimeError("POSTGRES_URL_NON_POOLING or POSTGRES_URL is required.")

    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("Install psycopg[binary] before running data retention.") from error

    deleted = {}
    with psycopg.connect(settings.postgres_url) as connection:
        with connection.cursor() as cursor:
            for table, age_column in RETENTION_TABLES:
                cursor.execute(
                    f"delete from public.{table} where {age_column} < now() - interval '7 days'"
                )
                deleted[table] = cursor.rowcount
        connection.commit()
    return {"ok": True, "retention_days": 7, "deleted_rows": deleted}

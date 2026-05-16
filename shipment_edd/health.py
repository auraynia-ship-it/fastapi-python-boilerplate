from pathlib import Path
from hashlib import sha256

from .config import get_edd_job_settings
from .supabase import SupabaseRestClient


REQUIRED_TABLES = (
    "app_migrations",
    "shipment_edd_job_runs",
    "shipment_snapshots",
    "shipment_edd_breaches",
)
MIGRATIONS_DIR = Path("db/migrations")
MIGRATION_TABLE = "app_migrations"


def check_edd_system_health():
    settings = get_edd_job_settings()
    supabase = SupabaseRestClient(settings.supabase_url, settings.supabase_key)

    table_checks = {}
    missing_tables = []
    for table in REQUIRED_TABLES:
        exists, error = supabase.table_exists(table)
        table_checks[table] = {
            "exists": exists,
            "schema": "public",
            "error": error,
        }
        if not exists:
            missing_tables.append(table)

    checks = {
        "supabase_configured": bool(settings.supabase_url and settings.supabase_key),
        "supabase_rest_reachable": any(
            table_check["exists"] for table_check in table_checks.values()
        ),
        "required_tables_exist": not missing_tables,
        "shiprocket_credentials_present": bool(
            settings.shiprocket_token
            or (settings.shiprocket_email and settings.shiprocket_password)
        ),
        "postgres_migration_configured": bool(settings.postgres_url),
    }

    return {
        "ok": all(
            (
                checks["supabase_configured"],
                checks["supabase_rest_reachable"],
                checks["required_tables_exist"],
                checks["shiprocket_credentials_present"],
            )
        ),
        "schema": "public",
        "checks": checks,
        "tables": table_checks,
        "missing_tables": missing_tables,
        "migration": {
            "can_run_from_api": bool(settings.postgres_url),
            "requires_package": "psycopg[binary]",
            "directory": str(MIGRATIONS_DIR),
            "table": f"public.{MIGRATION_TABLE}",
        },
    }


def run_edd_migration():
    settings = get_edd_job_settings()
    if not settings.postgres_url:
        raise RuntimeError(
            "POSTGRES_URL_NON_POOLING or POSTGRES_URL is required to run migrations."
        )

    if not MIGRATIONS_DIR.exists():
        raise RuntimeError(f"Migration directory not found: {MIGRATIONS_DIR}")

    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "Install psycopg[binary] before running migrations from the API."
        ) from error

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No migration files found in {MIGRATIONS_DIR}")

    applied = []
    skipped = []
    with psycopg.connect(settings.postgres_url) as connection:
        with connection.cursor() as cursor:
            ensure_migration_table(cursor)
            applied_migrations = get_applied_migrations(cursor)

            for migration_file in migration_files:
                migration_name = migration_file.name
                migration_sql = migration_file.read_text(encoding="utf-8")
                checksum = sha256(migration_sql.encode("utf-8")).hexdigest()

                if migration_name in applied_migrations:
                    skipped.append(migration_name)
                    continue

                cursor.execute(migration_sql)
                cursor.execute(
                    """
                    insert into public.app_migrations (filename, checksum)
                    values (%s, %s)
                    on conflict (filename) do nothing
                    """,
                    (migration_name, checksum),
                )
                applied.append(migration_name)

            cursor.execute("notify pgrst, 'reload schema'")
        connection.commit()

    health = check_edd_system_health()
    health["migration"]["applied"] = applied
    health["migration"]["skipped"] = skipped
    return health


def ensure_migration_table(cursor):
    cursor.execute(
        """
        create table if not exists public.app_migrations (
            id bigserial primary key,
            filename text not null unique,
            checksum text not null,
            applied_at timestamptz not null default now()
        )
        """
    )


def get_applied_migrations(cursor):
    cursor.execute("select filename from public.app_migrations")
    return {row[0] for row in cursor.fetchall()}

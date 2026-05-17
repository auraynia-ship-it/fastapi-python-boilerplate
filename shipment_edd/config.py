import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class EddJobSettings:
    shiprocket_token: str | None
    shiprocket_email: str | None
    shiprocket_password: str | None
    supabase_url: str | None
    supabase_key: str | None
    postgres_url: str | None
    cron_secret: str | None
    blob_rw_token: str | None
    blob_access: str
    blob_prefix: str
    order_window_days: int
    max_pages: int
    per_page: int
    report_dir: str
    timezone: str


def _int_env(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def get_edd_job_settings():
    is_vercel = bool(os.getenv("VERCEL"))
    default_report_dir = "/tmp/shipment_edd_reports" if is_vercel else "reports"

    return EddJobSettings(
        shiprocket_token=os.getenv("SHIPROCKET_TOKEN"),
        shiprocket_email=os.getenv("SHIPROCKET_EMAIL"),
        shiprocket_password=os.getenv("SHIPROCKET_PASSWORD"),
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=(
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
        ),
        postgres_url=(
            os.getenv("POSTGRES_URL_NON_POOLING")
            or os.getenv("POSTGRES_URL")
            or os.getenv("POSTGRES_PRISMA_URL")
        ),
        cron_secret=os.getenv("EDD_JOB_CRON_SECRET") or os.getenv("CRON_SECRET"),
        blob_rw_token=os.getenv("BLOB_READ_WRITE_TOKEN"),
        blob_access=os.getenv("EDD_REPORT_BLOB_ACCESS", "public"),
        blob_prefix=os.getenv("EDD_REPORT_BLOB_PREFIX", "edd-breach-reports"),
        order_window_days=_int_env("SHIPROCKET_ORDER_WINDOW_DAYS", 45),
        max_pages=_int_env("SHIPROCKET_MAX_PAGES", 20),
        per_page=_int_env("SHIPROCKET_PER_PAGE", 100),
        report_dir=os.getenv("EDD_REPORT_DIR", default_report_dir),
        timezone=os.getenv("EDD_JOB_TIMEZONE", "Asia/Kolkata"),
    )

"""Backward-compatible alias for app.cron_jobs.data_retention."""

import sys

from app.cron_jobs import data_retention as _implementation

sys.modules[__name__] = _implementation

"""Backward-compatible alias for app.config.settings."""

import sys

from app.config import settings as _implementation

sys.modules[__name__] = _implementation

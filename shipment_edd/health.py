"""Backward-compatible alias for app.health.edd."""

import sys

from app.health import edd as _implementation

sys.modules[__name__] = _implementation

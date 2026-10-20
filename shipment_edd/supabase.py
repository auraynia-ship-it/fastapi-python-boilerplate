"""Backward-compatible alias for app.database.supabase."""

import sys

from app.database import supabase as _implementation

sys.modules[__name__] = _implementation

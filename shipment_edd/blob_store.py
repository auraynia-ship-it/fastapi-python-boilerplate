"""Backward-compatible alias for app.storage.blob_store."""

import sys

from app.storage import blob_store as _implementation

sys.modules[__name__] = _implementation

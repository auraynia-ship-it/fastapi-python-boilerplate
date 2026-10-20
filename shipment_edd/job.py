"""Backward-compatible alias for app.shipment_edd.job."""

import sys

from app.shipment_edd import job as _implementation

sys.modules[__name__] = _implementation

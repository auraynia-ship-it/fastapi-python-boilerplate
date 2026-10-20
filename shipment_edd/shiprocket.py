"""Backward-compatible alias for app.shipment_edd.shiprocket."""

import sys

from app.shipment_edd import shiprocket as _implementation

sys.modules[__name__] = _implementation

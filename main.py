"""Backward-compatible FastAPI import; the application lives in app.main."""

from app.main import *  # noqa: F403
from app.main import app

__all__ = ["app"]

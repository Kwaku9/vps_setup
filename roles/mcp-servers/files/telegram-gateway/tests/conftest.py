"""Pytest bootstrap.

`telegram_gateway.config` reads several env vars at import time (it is written
for the container runtime, where they are always present). Seed harmless
defaults BEFORE any test imports the package so the suite can run outside a
container. Real values are never needed for unit tests.
"""
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("AUTH_TOKEN", "test-auth")

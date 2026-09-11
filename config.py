"""
config.py

Centralised application configuration. All values are read from environment
variables (via a local .env file during development) so that no secrets --
especially SSH credentials -- are ever hard-coded or exposed to the browser.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Router SSH connection settings ---
    ROUTER_HOST = os.getenv("ROUTER_HOST", "192.168.1.1")
    ROUTER_PORT = int(os.getenv("ROUTER_PORT", "22"))
    ROUTER_USERNAME = os.getenv("ROUTER_USERNAME", "root")
    ROUTER_PASSWORD = os.getenv("ROUTER_PASSWORD") or None
    ROUTER_KEY_PATH = os.getenv("ROUTER_KEY_PATH") or None

    SSH_CONNECT_TIMEOUT = int(os.getenv("SSH_CONNECT_TIMEOUT", "6"))
    SSH_COMMAND_TIMEOUT = int(os.getenv("SSH_COMMAND_TIMEOUT", "8"))

    # --- Flask server settings ---
    FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG = _as_bool(os.getenv("FLASK_DEBUG"), default=False)

    # --- Frontend / polling settings ---
    REFRESH_INTERVAL_MS = int(os.getenv("REFRESH_INTERVAL_MS", "5000"))
    CPU_HISTORY_LENGTH = int(os.getenv("CPU_HISTORY_LENGTH", "60"))

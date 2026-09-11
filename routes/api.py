"""
routes/api.py

Flask Blueprint exposing the REST API consumed by the dashboard frontend.
Every route here is READ-ONLY: it returns JSON describing router state.
No route accepts a command, parameter, or payload that could change
router configuration.
"""

from flask import Blueprint, jsonify

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _get_router_service():
    # Imported lazily to avoid circular imports; router_service is attached
    # to the Flask app in app.py (app.router_service).
    from flask import current_app

    return current_app.router_service


@api_bp.route("/system", methods=["GET"])
def get_system():
    """System Overview: CPU, RAM, uptime, hostname, kernel, Buildroot version."""
    router = _get_router_service()
    data = router.get_system_overview()
    status_code = 200 if data["status"] == "online" else 503
    return jsonify(data), status_code


@api_bp.route("/processes", methods=["GET"])
def get_processes():
    """Process Manager: full list of running processes on the router."""
    router = _get_router_service()
    data = router.get_processes()
    status_code = 200 if data["status"] == "online" else 503
    return jsonify(data), status_code


@api_bp.route("/network", methods=["GET"])
def get_network():
    """Network Information: interfaces, IPs, MACs, default gateway."""
    router = _get_router_service()
    data = router.get_network_info()
    status_code = 200 if data["status"] == "online" else 503
    return jsonify(data), status_code


@api_bp.route("/health", methods=["GET"])
def get_health():
    """Lightweight liveness check used for the Router Status indicator."""
    router = _get_router_service()
    data = router.check_health()
    status_code = 200 if data["status"] == "online" else 503
    return jsonify(data), status_code

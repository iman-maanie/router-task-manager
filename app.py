"""
app.py

Application entrypoint for Router Task Manager.

Architecture reminder:

    Browser  <--HTTP/JSON-->  Flask Backend  <--SSH-->  ConnectCo Router

The browser NEVER talks to the router directly and NEVER sees SSH
credentials -- those live only in this backend process (loaded from .env).
"""

from flask import Flask, render_template
from flask_cors import CORS

from config import Config
from services.router_service import RouterService
from routes.api import api_bp


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    # One shared RouterService instance for the whole app -- it manages a
    # single reusable SSH connection rather than opening a new one per request.
    app.router_service = RouterService()

    app.register_blueprint(api_bp)

    @app.route("/")
    def dashboard():
        return render_template("index.html", refresh_ms=Config.REFRESH_INTERVAL_MS)

    @app.teardown_appcontext
    def _cleanup(exception=None):
        # Connection is intentionally kept alive across requests for
        # performance; it is only closed on process shutdown (see below).
        pass

    return app


app = create_app()


if __name__ == "__main__":
    try:
        app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG)
    finally:
        app.router_service.close()

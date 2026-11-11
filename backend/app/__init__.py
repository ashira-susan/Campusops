import importlib, pkgutil, os
from flask import Flask, g, jsonify, send_from_directory
from . import config, db
from .util import ApiError

def create_app(overrides=None):
    root = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
    app = Flask(__name__, static_folder=None)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    app.config.update(overrides or {})
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY is not set (see .env.example)")

    @app.before_request
    def _open():
        g.db = db.connect(app.config.get("DB_PATH"))

    @app.teardown_request
    def _close(exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return jsonify(error=e.code, message=e.message, **e.extra), e.status

    @app.errorhandler(404)
    def _nf(e):
        return jsonify(error="not_found", message="No such resource"), 404

    from . import routes
    for m in pkgutil.iter_modules(routes.__path__):      # every module in routes/ exposes `bp`
        mod = importlib.import_module(f"{__name__}.routes.{m.name}")
        if hasattr(mod, "bp"):
            app.register_blueprint(mod.bp)

    @app.get("/")
    def _index():
        return send_from_directory(root, "index.html")

    @app.get("/static/<path:name>")
    def _static(name):
        return send_from_directory(root, name)
    return app

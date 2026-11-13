"""Entry point. Threaded Werkzeug server (adequate for the bounded first release; see README limitations)."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from werkzeug.serving import run_simple
from app import create_app

if __name__ == "__main__":
    app = create_app()
    run_simple(os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "5000")), app, threaded=True)

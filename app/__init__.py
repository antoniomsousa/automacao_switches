import os

from flask import Flask, url_for
from flask_wtf.csrf import CSRFProtect

# Company logo: drop the official file in app/static/img/ with one of these names
LOGOS_EMPRESA = ("logo-meli.svg", "logo-meli.png")


def create_app():
    app = Flask(__name__)
    # Signs the session that holds the CSRF token; random by default, so a restart invalidates open forms
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(32)
    # Token valid for the whole session, not just 1h, so a form left open still submits
    app.config["WTF_CSRF_TIME_LIMIT"] = None
    CSRFProtect(app)

    from app.controllers.switch_controller import bp as switch_bp
    app.register_blueprint(switch_bp)

    @app.context_processor
    def logo_empresa():
        for nome in LOGOS_EMPRESA:
            if os.path.exists(os.path.join(app.static_folder, "img", nome)):
                return {"logo_empresa": url_for("static", filename="img/" + nome)}
        return {"logo_empresa": None}

    return app

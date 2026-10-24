import os

from flask import Flask, url_for

# Company logo: drop the official file in app/static/img/ with one of these names
LOGOS_EMPRESA = ("logo-meli.svg", "logo-meli.png")


def create_app():
    app = Flask(__name__)

    from app.controllers.switch_controller import bp as switch_bp
    app.register_blueprint(switch_bp)

    @app.context_processor
    def logo_empresa():
        for nome in LOGOS_EMPRESA:
            if os.path.exists(os.path.join(app.static_folder, "img", nome)):
                return {"logo_empresa": url_for("static", filename="img/" + nome)}
        return {"logo_empresa": None}

    return app

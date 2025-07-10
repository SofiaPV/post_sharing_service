def create_app():
    from flask import Flask
    from .routes import main_routes

    app = Flask(__name__)
    app.register_blueprint(main_routes)
    return app

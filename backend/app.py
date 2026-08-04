from flask import Flask
from routes.isochrone import isochrone_bp
from routes.geocode import geocode_bp
from routes.poi_stat import poi_stat_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(isochrone_bp)
    app.register_blueprint(geocode_bp)
    app.register_blueprint(poi_stat_bp)
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)

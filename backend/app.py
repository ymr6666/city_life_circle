from flask import Flask
from routes.isochrone import isochrone_bp
from routes.geocode import geocode_bp
from routes.poi_stat import poi_stat_bp
from routes.roads import roads_bp
from routes.score import score_bp
from routes.grid import grid_bp
from routes.regeo import regeo_bp
from routes.tiles import tiles_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(isochrone_bp)
    app.register_blueprint(geocode_bp)
    app.register_blueprint(poi_stat_bp)
    app.register_blueprint(roads_bp)
    app.register_blueprint(score_bp)
    app.register_blueprint(grid_bp)
    app.register_blueprint(regeo_bp)
    app.register_blueprint(tiles_bp)

    # CORS: 允许前端 (file:// 打开 viewer.html 或其它域名) 跨域调用 API
    @app.after_request
    def add_cors_headers(resp):
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)

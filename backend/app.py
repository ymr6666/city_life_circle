from flask import Flask, send_from_directory
from pathlib import Path
from routes.isochrone import isochrone_bp
from routes.geocode import geocode_bp
from routes.poi_stat import poi_stat_bp
from routes.roads import roads_bp
from routes.score import score_bp
from routes.grid import grid_bp
from routes.regeo import regeo_bp
from routes.tiles import tiles_bp
from routes.coverage import coverage_bp
from routes.planning import planning_bp
from routes.population import population_bp
from routes.citywide import citywide_bp

# 前端构建产物目录 (存在则后端直接托管, 无需 nginx; 本地一键运行)
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app():
    static_folder = None
    static_url_path = None
    if FRONTEND_DIST.is_dir():
        static_folder = str(FRONTEND_DIST / "assets")
        static_url_path = "/assets"

    app = Flask(__name__,
                static_folder=static_folder,
                static_url_path=static_url_path)

    app.register_blueprint(isochrone_bp)
    app.register_blueprint(geocode_bp)
    app.register_blueprint(poi_stat_bp)
    app.register_blueprint(roads_bp)
    app.register_blueprint(score_bp)
    app.register_blueprint(grid_bp)
    app.register_blueprint(regeo_bp)
    app.register_blueprint(tiles_bp)
    app.register_blueprint(coverage_bp)
    app.register_blueprint(planning_bp)
    app.register_blueprint(population_bp)
    app.register_blueprint(citywide_bp)

    # CORS: 允许前端开发服务器/部署域名跨域调用 API
    @app.after_request
    def add_cors_headers(resp):
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    # 生产模式: 后端托管构建好的前端 (单页应用入口)
    if FRONTEND_DIST.is_dir():
        @app.route('/')
        def index():
            return send_from_directory(FRONTEND_DIST, 'index.html')

    return app


def run_production(app, host='0.0.0.0', port=5000):
    """生产运行: 优先 waitress (Windows/Linux 通用), 缺失时回退 Flask dev server。"""
    try:
        from waitress import serve
        print(f"[serve] waitress on http://{host}:{port}")
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        print("[serve] waitress 未安装, 使用 Flask 开发服务器 (仅限演示/调试)")
        app.run(host=host, port=port)


if __name__ == '__main__':
    app = create_app()
    run_production(app)

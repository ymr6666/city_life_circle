"""栅格瓦片 API: 人口密度底图 XYZ 瓦片

GET /tiles/pop/{z}/{x}/{y}.png
从 cache/pop_tiles 读取预生成瓦片 (scripts/utils/build_pop_tiles.py 生成)。
"""
from pathlib import Path

from flask import Blueprint, send_file, abort

tiles_bp = Blueprint('tiles', __name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TILE_ROOT = PROJECT_ROOT / "cache" / "pop_tiles"

VALID_SETS = {"pop"}


@tiles_bp.route('/tiles/<tileset>/<int:z>/<int:x>/<int:y>.png')
def tile(tileset, z, x, y):
    if tileset not in VALID_SETS:
        abort(404)
    # 瓦片目录结构: cache/pop_tiles/{z}/{x}/{y}.png
    p = TILE_ROOT / str(z) / str(x) / f"{y}.png"
    if not p.is_file():
        abort(404)
    return send_file(p, mimetype='image/png', max_age=86400)

import requests
from config import AMAP_KEY

tests = [
    ("医院-无types", {"keywords": "医院", "city": "合肥"}),
    ("医院-types=080100", {"keywords": "医院", "types": "080100", "city": "合肥"}),
    ("中学-无types", {"keywords": "中学", "city": "合肥"}),
    ("中学-types=141300", {"keywords": "中学", "types": "141300", "city": "合肥"}),
]

for label, params in tests:
    params["key"] = AMAP_KEY
    params["offset"] = 5
    params["page"] = 1
    params["extensions"] = "all"
    r = requests.get("https://restapi.amap.com/v3/place/text", params=params, headers={"User-Agent":"test"}, timeout=15)
    d = r.json()
    first = d["pois"][0] if d.get("pois") else None
    typecode = first.get("typecode", "N/A") if first else "N/A"
    print(f"{label:25s} count={d.get('count',0):>5}  sample: {first['name'] if first else 'None'} (typecode={typecode})")

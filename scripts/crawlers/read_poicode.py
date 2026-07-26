import pandas as pd, glob, os

base = r"C:\Users\yummy\Downloads\Amap_poicode"
files = glob.glob(os.path.join(base, "*.xlsx"))
files = [f for f in files if not os.path.basename(f).startswith("._")]

df = pd.read_excel(files[0], header=None)
out = []
for _, r in df.iterrows():
    line = " ".join([str(v) for v in r.values if str(v) != "nan"])
    keywords = ["医院","小学","中学","公园","商城","购物","超市","地铁","公交","商场"]
    if any(w in line for w in keywords):
        out.append(line)

with open("poicode_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"已写入 {len(out)} 行到 poicode_result.txt")

import requests, time
h = {"User-Agent": "Mozilla/5.0"}
url = "https://overpass.kumi.systems/api/interpreter"

q_new = '[out:json][timeout:30];node(31.68,117.07,32.07,117.50)[railway=station][station=subway];out count;'
r = requests.post(url, data={"data": q_new}, headers=h, timeout=60)
n_new = r.json()["elements"][0].get("tags", {}).get("total", "?")
print(f"New bbox: {n_new} stations")

time.sleep(1)
q_old = '[out:json][timeout:30];node(31.7,117.1,32.0,117.5)[railway=station][station=subway];out count;'
r2 = requests.post(url, data={"data": q_old}, headers=h, timeout=60)
n_old = r2.json()["elements"][0].get("tags", {}).get("total", "?")
print(f"Old bbox: {n_old} stations")
print(f"Diff: {int(n_new) - int(n_old)}")

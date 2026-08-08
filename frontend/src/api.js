const BASE = '/api'

async function postJson(url, body) {
  const r = await fetch(BASE + url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  return { ok: r.ok, status: r.status, data }
}

async function getJson(url) {
  const r = await fetch(BASE + url)
  const data = await r.json().catch(() => ({}))
  return { ok: r.ok, status: r.status, data }
}

export const api = {
  geocode: (keywords, limit = 5) =>
    getJson(`/geocode?keywords=${encodeURIComponent(keywords)}&region=合肥&limit=${limit}`),
  regeo: (lat, lng, poinums = 3) =>
    getJson(`/regeo?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}&poinums=${poinums}`),
  isochrone: (lat, lng, mode, time, snapRadius = 150) =>
    postJson('/isochrone', { lat, lng, mode, time_budget_min: time, snap_radius_m: snapRadius }),
  reverse: (facilities, mode, time, snapRadius = 150) =>
    postJson('/reverse-isochrone', { facilities, mode, time_budget_min: time, snap_radius_m: snapRadius }),
  poiStat: (polygon, includeItems = false) =>
    postJson('/poi-stat', { polygon, include_items: includeItems }),
  score: (lat, lng, mode, time, weights = null, family = 'none', snapRadius = 150) =>
    postJson('/score', { lat, lng, mode, time_budget_min: time, snap_radius_m: snapRadius, weights, family }),
  grid: (bbox, cellSizeDeg = 0.01, metric = 'score', category = null) =>
    postJson('/grid', { bbox, cell_size_deg: cellSizeDeg, metric, category }),
  roads: (bounds, mode = 'all') => {
    const q = `minlng=${bounds.getWest()}&minlat=${bounds.getSouth()}` +
      `&maxlng=${bounds.getEast()}&maxlat=${bounds.getNorth()}&mode=${mode}`
    return getJson(`/roads?${q}`)
  },
}

// 地址取点: 优先用库内 address, 缺失时用高德逆地理编码
export async function fetchAddress(lat, lng) {
  const r = await api.regeo(lat, lng)
  if (r.ok && r.data && r.data.address) return r.data.address
  return ''
}

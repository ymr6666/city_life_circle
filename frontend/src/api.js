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
  grid: (bbox, cellSizeDeg = 0.01, metric = 'score', category = null, gridType = 'hex') =>
    postJson('/grid', { bbox, cell_size_deg: cellSizeDeg, metric, category, grid_type: gridType }),
  coverage: (body) => postJson('/coverage', body),
  coverageCurve: (lat, lng, mode, timeBudgets = [5, 10, 15, 20, 30]) =>
    postJson('/coverage-curve', { lat, lng, mode, time_budgets: timeBudgets }),
  blindzone: (category, mode = 'walk', timeBudgetMin = 15, bbox = null, cellSizeDeg = 0.001, gridType = 'square', pointMode = true, maxPoints = 15000, tier = null) =>
    postJson('/blindzone', { category, mode, time_budget_min: timeBudgetMin, bbox, cell_size_deg: cellSizeDeg, grid_type: gridType, point_mode: pointMode, max_points: maxPoints, tier }),
  planningClosure: (poiIds, mode = 'walk', timeBudgetMin = 15, fallback = 30, otherCategory = null, tier = null, facilityIds = null) =>
    postJson('/planning/closure', { poi_ids: poiIds, facility_ids: facilityIds, mode, time_budget_min: timeBudgetMin, fallback_time_min: fallback, other_category: otherCategory, tier }),
  planningRelocation: (oldPoiId, newLat, newLng, mode = 'walk', timeBudgetMin = 15, oldFacilityId = null, tier = null) =>
    postJson('/planning/relocation', { old_poi_id: oldPoiId, old_facility_id: oldFacilityId, new_lat: newLat, new_lng: newLng, mode, time_budget_min: timeBudgetMin, tier }),
  planningSiteSelection: (category, mode = 'walk', timeBudgetMin = 15, bbox = null, nCandidates = 10, extraCandidates = [], auto = true, tier = null) =>
    postJson('/planning/site-selection', { category, mode, time_budget_min: timeBudgetMin, bbox, n_candidates: nCandidates, extra_candidates: extraCandidates, auto, tier }),
  roads: (bounds, mode = 'all') => {
    const q = `minlng=${bounds.getWest()}&minlat=${bounds.getSouth()}` +
      `&maxlng=${bounds.getEast()}&maxlat=${bounds.getNorth()}&mode=${mode}`
    return getJson(`/roads?${q}`)
  },
  populationStat: (bbox = null, polygon = null) =>
    postJson('/population/stat', { bbox, polygon }),
  populationResidential: (bbox = null, limit = 500) =>
    postJson('/population/residential', { bbox, limit }),
  citywideClusters: (category, mode = 'walk', timeBudgetMin = 15, bbox = null, tier = null, clusterCellDeg = 0.0025, minPoints = 5, topN = 20, connectivity = 4) =>
    postJson('/citywide/clusters', { category, mode, time_budget_min: timeBudgetMin, bbox, tier, cluster_cell_deg: clusterCellDeg, min_points: minPoints, top_n: topN, connectivity }),
  citywideMismatch: (category, bbox = null, tier = null, cellSizeDeg = 0.01, gridType = 'hex') =>
    postJson('/citywide/mismatch', { category, bbox, tier, cell_size_deg: cellSizeDeg, grid_type: gridType }),
  citywideBalance: (category, mode = 'walk', timeBudgetMin = 15, bbox = null, tier = null) =>
    postJson('/citywide/balance', { category, mode, time_budget_min: timeBudgetMin, bbox, tier }),
}

// 地址取点: 优先用库内 address, 缺失时用高德逆地理编码
export async function fetchAddress(lat, lng) {
  const r = await api.regeo(lat, lng)
  if (r.ok && r.data && r.data.address) return r.data.address
  return ''
}

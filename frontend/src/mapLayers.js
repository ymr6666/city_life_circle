import L from 'leaflet'
import * as turf from '@turf/turf'
import { store, CAT_COLORS } from './store'

// 当前全部叠加图层 (清空用)
const overlays = []
// 常驻的"当前位置"标记 (不随 clearOverlays 清除)
let currentPointLayer = null

export function clearOverlays() {
  while (overlays.length) overlays.pop().remove()
}

export function addOverlay(layer) {
  overlays.push(layer)
  layer.addTo(store.map)
}

export function addGeoJson(data, style) {
  const l = L.geoJSON(data, { style })
  addOverlay(l)
  return l
}

function pts2fc(points) {
  return {
    type: 'FeatureCollection',
    features: points.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
    })),
  }
}

// 均匀抽样: 超过 max 个点则取子集 (降低画布渲染量)
function samplePoints(points, max) {
  if (points.length <= max) return points
  const step = Math.ceil(points.length / max)
  return points.filter((_, i) => i % step === 0)
}

export function addPointLayer(points, color, radius, opacity) {
  const l = L.geoJSON(pts2fc(points), {
    pointToLayer: (f, ll) =>
      L.circleMarker(ll, { radius, color, fillColor: color, fillOpacity: opacity, weight: 1 }),
    
  })
  addOverlay(l)
  return l
}

function esc(s) {
  return String(s || '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c])
}

function popupHtml(name, address, sub) {
  const addr = address ? `<div class="fac-pop-addr">${esc(address)}</div>` : ''
  const subLine = sub ? `<div class="fac-pop-sub">${esc(sub)}</div>` : ''
  return `<b>${esc(name)}</b>${addr}${subLine}`
}

// ---------- 当前位置常驻标记 ----------
// 用 L.marker + divIcon (DOM 标记), 缩放/平移时必然跟随地图;
// 永久 tooltip 在 preferCanvas 下定位不稳定, 弃用
function pointDivIcon(color, label) {
  const lbl = label ? `<div class="pt-lbl">${esc(label)}</div>` : ''
  return L.divIcon({
    className: 'pt-icon',
    html: `<div class="pt-pin" style="background:${color}"></div>${lbl}`,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  })
}

export function setCurrentPoint(lat, lng, label) {
  clearCurrentPoint()
  if (!store.map) return
  currentPointLayer = L.marker([lat, lng], {
    icon: pointDivIcon('#e53935', label || ''),
    zoomAnimation: false,   // 缩放时直接定位, 避免连续滚动的偏移
  }).addTo(store.map)
}

export function clearCurrentPoint() {
  if (currentPointLayer) { currentPointLayer.remove(); currentPointLayer = null }
}

// 选点模式: 地图容器十字光标
export function setPickMode(on) {
  if (store.map) store.map.getContainer().classList.toggle('pick-mode', on)
}

// ---------- 设施点图层 (带名称/地址弹窗) ----------
function facilityFC(items) {
  return {
    type: 'FeatureCollection',
    features: items.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
      properties: {
        name: p.name || '', address: p.address || '',
        sub_category: p.sub_category || '', count: p.count || 1,
      },
    })),
  }
}

export function addFacilityLayer(items, color, radius = 4) {
  const l = L.geoJSON(facilityFC(items), {
    pointToLayer: (f, ll) => L.circleMarker(ll, {
      radius, color: '#fff', weight: 1, fillColor: color, fillOpacity: 0.9,
    }),
    
  })
  l.eachLayer((ly) => {
    const p = ly.feature.properties
    if (!p.name) return
    ly.bindPopup(popupHtml(p.name, p.address, p.sub_category), { maxWidth: 280 })
  })
  addOverlay(l)
  return l
}

// 聚焦某个设施: 地图定位 + 打开地址弹窗
export function focusFacility(f) {
  if (!store.map) return
  const ll = [f.lat, f.lng]
  store.map.setView(ll, Math.max(store.map.getZoom(), 16))
  L.popup({ maxWidth: 280 })
    .setLatLng(ll)
    .setContent(popupHtml(f.name, f.address, f.sub_category))
    .openOn(store.map)
}

// 带标签的标记 (分析点用, 随 clearOverlays 清除)
export function addLabeledMarker(lat, lng, label, color) {
  const mk = L.marker([lat, lng], {
    icon: pointDivIcon(color, label),
    zoomAnimation: false,   // 缩放时直接定位, 避免连续滚动的偏移
  })
  addOverlay(mk)
  return mk
}

// ---------- 正算等时圈 ----------
export function drawIsochrone(d, opts = {}) {
  const {
    showPoints = true, showFacilities = true, color = '#1976d2',
    outlineOnly = false,
  } = opts
  const nodes = d.reachable_nodes || d.reachable_road_nodes || []

  if (d.polygon) {
    addGeoJson(d.polygon, {
      color: color, weight: 2.5, fillColor: color, fillOpacity: outlineOnly ? 0.04 : 0.10,
      
    })
  }
  if (!outlineOnly && showPoints && nodes.length) {
    // 点云抽样: 降量减少 SVG 元素数量 (卡顿主因)
    const MAX_POINTS = 1500
    const step = Math.ceil(nodes.length / MAX_POINTS)
    const sampled = step > 1 ? nodes.filter((_, i) => i % step === 0) : nodes
    addPointLayer(sampled, color, 2, 0.3)
  }
  if (!outlineOnly && showFacilities) {
    // 设施粒度 (facility_id 去重) 渲染, 每类最多 150 个, 带地址弹窗
    const cats = d.facilities_by_category || {}
    for (const [cat, info] of Object.entries(cats)) {
      const items = (info.items || []).slice(0, 150)
      if (items.length) {
        addFacilityLayer(items, CAT_COLORS[cat] || '#607d8b')
      }
    }
  }
  if (!outlineOnly && d.reachable_metro_stations && d.reachable_metro_stations.length) {
    addPointLayer(d.reachable_metro_stations, '#009688', 5, 0.9)
  }
  if (!outlineOnly && d.reachable_bus_stops && d.reachable_bus_stops.length) {
    addPointLayer(samplePoints(d.reachable_bus_stops, 400), '#ff7043', 2, 0.5)
  }
}

// ---------- 反算覆盖/选址 ----------
export function drawReverse(d, opts = {}) {
  const fs = d.facilities || []
  const labels = opts.facilities || []
  fs.forEach((f, i) => {
    if (f.polygon) {
      addGeoJson(f.polygon, {
        color: '#1565c0', weight: 2, fillColor: '#1976d2', fillOpacity: 0.15,
      })
    }
    // 设施标记 + 地址标签
    const info = labels[i] || {}
    const mk = L.marker([f.lat, f.lng], {
      icon: pointDivIcon('#1565c0', info.address || info.name || `设施 ${i + 1}`),
      zoomAnimation: false,
    })
    addOverlay(mk)
  })
  if (d.intersection && d.intersection.polygon) {
    addGeoJson(d.intersection.polygon, {
      color: '#2e7d32', weight: 2, fillColor: '#2e7d32', fillOpacity: 0.3,
    })
  }
}

// ---------- 路网 (视口动态) ----------
let roadLayer = null
let roadTimer = null
let roadMode = 'all'
let roadEnabled = false

export function clearRoads() {
  clearTimeout(roadTimer)
  roadTimer = null
  roadEnabled = false
  if (roadLayer) { roadLayer.remove(); roadLayer = null }
}

export function loadRoads(mode = roadMode) {
  clearTimeout(roadTimer)
  roadMode = mode
  roadEnabled = true
  const b = store.map.getBounds()
  fetch(`/api/roads?minlng=${b.getWest()}&minlat=${b.getSouth()}` +
    `&maxlng=${b.getEast()}&maxlat=${b.getNorth()}&mode=${mode}`)
    .then((r) => r.json())
    .then((j) => {
      // 取消勾选后不应再添加 (飞行中的 fetch 也要被守卫拦截)
      if (!roadEnabled) return
      if (roadLayer) { roadLayer.remove(); roadLayer = null }
      if (j && j.features && j.features.length) {
        roadLayer = L.geoJSON(j, {
          pane: 'roads',
          style: (f) => ({ color: roadColor(f.properties.highway), weight: 1.2, opacity: 0.7 }),
          interactive: false,
        }).addTo(store.map)
      }
    })
    .catch(() => {})
}

function roadColor(highway) {
  const h = (highway || '').toLowerCase()
  if (h.includes('motorway') || h.includes('trunk')) return '#e57373'
  if (h.includes('primary')) return '#ffb74d'
  if (h.includes('secondary')) return '#ffd54f'
  if (h.includes('tertiary') || h.includes('residential')) return '#90a4ae'
  return '#b0bec5'
}

export function scheduleRoads(mode) {
  clearTimeout(roadTimer)
  roadEnabled = true
  roadTimer = setTimeout(() => loadRoads(mode), 350)
}

// ---------- 六边形分级色彩 ----------
export function drawHexGrid(fc, colorRamp) {
  return addGeoJson(fc, (f) => {
    const s = f.properties.score
    return {
      color: 'rgba(0,0,0,0.10)', weight: 0.7, fillColor: colorRamp(s), fillOpacity: 0.8,
    }
  })
}

// 连续色阶 (白 → 蓝 → 深蓝), 专业 GIS 风格 (综合评分用)
export function scoreRamp(v) {
  const t = Math.max(0, Math.min(1, v / 100))
  const stops = [
    [0.00, '#f5f8fb'],
    [0.20, '#dbe7f4'],
    [0.40, '#aecdea'],
    [0.60, '#7ab2e0'],
    [0.80, '#3f8fd0'],
    [1.00, '#0f62b5'],
  ]
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1]
      const [t1, c1] = stops[i]
      const k = (t - t0) / (t1 - t0 || 1)
      return lerpColor(c0, c1, k)
    }
  }
  return stops[stops.length - 1][1]
}

// 人口密度色阶 (黄 → 橙 → 红), 经典人口分层设色 (人/km²)
export function popRamp(v) {
  const stops = [
    [0, '#ffffcc'],
    [3000, '#ffeda0'],
    [6000, '#fed976'],
    [12000, '#feb24c'],
    [20000, '#fd8d3c'],
    [30000, '#f03b20'],
    [50000, '#bd0026'],
  ]
  if (v <= stops[0][0]) return stops[0][1]
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i][0]) {
      const [t0, c0] = stops[i - 1]
      const [t1, c1] = stops[i]
      const k = (v - t0) / (t1 - t0 || 1)
      return lerpColor(c0, c1, k)
    }
  }
  return stops[stops.length - 1][1]
}

// 网格图例生成 (分段色块)
export function rampLegend(ramp, breaks, fmt) {
  const items = []
  for (let i = 0; i < breaks.length; i++) {
    const lo = breaks[i]
    const hi = i < breaks.length - 1 ? breaks[i + 1] : null
    const mid = hi === null ? lo : (lo + hi) / 2
    items.push({
      color: ramp(mid),
      label: hi === null
        ? `≥ ${fmt ? fmt(lo) : lo}`
        : `${fmt ? fmt(lo) : lo} ~ ${fmt ? fmt(hi) : hi}`,
    })
  }
  return items
}

function lerpColor(c1, c2, k) {
  const a = hex2rgb(c1), b = hex2rgb(c2)
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * k))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}
function hex2rgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
}

// turf 兜底: 点集凸包 (用于无 polygon 时)
export function hullGeojson(points) {
  if (points.length < 3) return null
  try { return turf.convex(pts2fc(points)) } catch { return null }
}

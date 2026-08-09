<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import L from 'leaflet'
import { store, togglePopLayer } from '../store'
import { popRamp, popDotRamp, rampLegend, addGeoJson, clearOverlays, setPickMode, addOverlay } from '../mapLayers'
import { api } from '../api'

const status = ref('就绪')
const enabled = computed(() => store.popOn)
const subtab = ref('density')    // density / stat / grid / residential

// 区域统计
const centerLat = ref(store.pointLat)
const centerLng = ref(store.pointLng)
const radiusKm = ref(3)
const picking = ref(false)
const statResult = ref(null)
const pickFor = ref(null)
const drawMode = ref(false)       // 手绘多边形模式
const polyPoints = ref([])        // 多边形顶点
const polyLayer = ref(null)       // 临时多边形图层
const polyResult = ref(null)      // 手绘多边形统计结果

// 网格人口
const gridSize = ref(0.005)
const gridResult = ref(null)

// 小区分布
const resiResult = ref(null)

// 瓦片色阶阈值 (人/格 ≈ 0.008km²), 与 build_pop_tiles.py 一致
const RAMP_BREAKS = [0, 2, 8, 20, 50, 120, 250, 500]
const fmt = (v) => (v >= 10000 ? (v / 10000).toFixed(1) + '万' : String(v))

function toggle() {
  togglePopLayer()
  status.value = store.popOn
    ? '已叠加人口密度图层（预渲染瓦片，任意缩放无需重新计算）'
    : '已移除人口密度图层'
}

function fitHefei() {
  if (store.map) store.map.fitBounds([[31.55, 116.95], [32.20, 117.62]])
  status.value = '已定位到合肥全域'
}

function updateLegend() {
  const legend = document.getElementById('pop-legend')
  if (!legend) return
  const items = rampLegend(popRamp, RAMP_BREAKS, fmt)
  legend.innerHTML = items
    .map((it) => `<div class="lrow"><span class="swatch" style="background:${it.color}"></span><span class="ltxt">${it.label}</span></div>`)
    .join('')
}

function currentBBox() {
  const dLat = radiusKm.value / 111.32
  const dLng = radiusKm.value / (111.32 * Math.cos((centerLat.value * Math.PI) / 180))
  return [centerLng.value - dLng, centerLat.value - dLat, centerLng.value + dLng, centerLat.value + dLat]
}

function renderStatBox() {
  const b = currentBBox()
  addOverlay(L.rectangle([[b[1], b[0]], [b[3], b[2]]], {
    color: '#0d47a1', weight: 2, dashArray: '6,4', fill: false, opacity: 0.85,
  }))
  addOverlay(L.circleMarker([centerLat.value, centerLng.value], {
    radius: 6, color: '#0d47a1', weight: 2, fillColor: '#1976d2', fillOpacity: 0.9,
  }))
}

// 区域统计 (bbox 或手绘多边形)
async function runStat() {
  status.value = '统计区域人口…'
  let bbox = null
  let polygon = null
  if (polyPoints.value.length >= 3) {
    polygon = {
      type: 'Polygon',
      coordinates: [[...polyPoints.value.map((p) => [p.lng, p.lat]), polyPoints.value[0] && [polyPoints.value[0].lng, polyPoints.value[0].lat]]],
    }
  } else {
    bbox = currentBBox()
  }
  const r = await api.populationStat(bbox, polygon)
  if (!r.ok) { status.value = `统计失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  if (polygon) renderPolygon()
  else renderStatBox()
  statResult.value = r.data
  status.value = `区域人口 ${r.data.population.toLocaleString()} 人 | ${r.data.area_km2} km² | 密度 ${r.data.density_per_km2.toLocaleString()}/km²`
}

// 手绘多边形
function startDraw() {
  if (drawMode.value) { stopDraw(); return }
  drawMode.value = true
  polyPoints.value = []
  setPickMode(true)
  status.value = '绘制模式：点击地图添加顶点，双击结束多边形'
  const container = store.map.getContainer()
  const clickListener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation(); e.preventDefault()
    const ll = store.map.mouseEventToLatLng(e)
    polyPoints.value.push({ lat: +ll.lat.toFixed(6), lng: +ll.lng.toFixed(6) })
    renderPolygon()
    status.value = `已添加 ${polyPoints.value.length} 个顶点 (双击结束)`
  }
  const dblListener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation(); e.preventDefault()
    finishDraw()
  }
  pickListenerRef.value = clickListener
  drawDblRef.value = dblListener
  container.addEventListener('click', clickListener, true)
  container.addEventListener('dblclick', dblListener, true)
}

function renderPolygon() {
  clearOverlays()
  if (!polyPoints.value.length) return
  const pts = polyPoints.value
  const mk = L.polygon(pts.map((p) => [p.lat, p.lng]), {
    color: '#0d47a1', weight: 2, fillColor: '#1976d2', fillOpacity: 0.15, dashArray: '4,4',
  })
  addOverlay(mk)
  // 顶点标记
  pts.forEach((p) => {
    addOverlay(L.circleMarker([p.lat, p.lng], {
      radius: 4, color: '#fff', weight: 1, fillColor: '#d32f2f', fillOpacity: 1,
    }))
  })
}

function finishDraw() {
  exitPick()
  drawMode.value = false
  if (polyPoints.value.length < 3) {
    polyPoints.value = []
    status.value = '顶点不足 3 个，已取消'
    return
  }
  renderPolygon()
  status.value = `多边形完成 (${polyPoints.value.length} 个顶点)，点「统计区域人口」`
}

function stopDraw() {
  exitPick()
  drawMode.value = false
}

function clearPolygon() {
  polyPoints.value = []
  polyResult.value = null
  if (drawMode.value) stopDraw()
  clearOverlays()
  status.value = '已清除多边形'
}

function pickCenter() {
  picking.value = true
  pickFor.value = 'stat'
  setPickMode(true)
  status.value = '选点模式：点击地图设置统计中心'
  const container = store.map.getContainer()
  const listener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation(); e.preventDefault()
    const ll = store.map.mouseEventToLatLng(e)
    exitPick()
    centerLat.value = +ll.lat.toFixed(6)
    centerLng.value = +ll.lng.toFixed(6)
    status.value = `统计中心已设为 ${centerLat.value.toFixed(5)}, ${centerLng.value.toFixed(5)}`
  }
  pickListenerRef.value = listener
  container.addEventListener('click', listener, true)
}

// 网格人口 choropleth
async function runGridPop() {
  status.value = '计算网格人口…'
  const r = await api.grid(currentBBox(), gridSize.value, 'population', null, 'square')
  if (!r.ok) { status.value = `网格失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  renderStatBox()
  // 人口密度分级色: 复用 popRamp
  const l = addGeoJson(r.data, (f) => {
    const dens = f.properties.density || 0
    return { color: 'rgba(0,0,0,0.12)', weight: 0.7, fillColor: popRamp(dens), fillOpacity: 0.8 }
  })
  l.eachLayer((ly) => {
    const p = ly.feature.properties
    ly.bindPopup(
      `<div class="pop-pop"><div class="pp-title">人口网格</div>` +
      `人口 <b>${p.population.toLocaleString()}</b><br/>` +
      `密度 <b>${Math.round(p.density).toLocaleString()}</b>/km²<br/>` +
      `面积 <b>${p.area_km2}</b> km²</div>`, { maxWidth: 240 })
  })
  gridResult.value = r.data
  status.value = `网格人口 | 密度区间 0 ~ ${Math.round(Math.max(...r.data.features.map((f) => f.properties.density || 0))).toLocaleString()}/km²`
}

// 小区人口分布
async function runResidential() {
  status.value = '加载小区人口…'
  const r = await api.populationResidential(currentBBox(), 600)
  if (!r.ok) { status.value = `加载失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  renderStatBox()
  const items = r.data.items
  // 按人口分级着色 (色阶: 少→多)
  const maxPop = Math.max(...items.map((x) => x.population), 1)
  const fc = {
    type: 'FeatureCollection',
    features: items.map((x) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [x.lng, x.lat] },
      properties: x,
    })),
  }
  const l = addGeoJson(fc, (f) => {
    const t = f.properties.population / maxPop
    return {
      color: 'rgba(0,0,0,0)', weight: 0,
      fillColor: popDotRamp(t), fillOpacity: 0.9,
      radius: 3 + t * 5,
    }
  }, { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4 }) })
  l.eachLayer((ly) => {
    const p = ly.feature.properties
    ly.bindPopup(
      `<div class="pop-pop"><div class="pp-title">${p.name || '(小区)'}</div>` +
      `估算人口 <b>${p.population.toLocaleString()}</b></div>`, { maxWidth: 240 })
  })
  resiResult.value = r.data
  status.value = `${r.data.n_residential} 个小区 | 估算总人口 ${r.data.estimated_total_population.toLocaleString()}`
}

function onClear() {
  clearOverlays()
  statResult.value = null
  gridResult.value = null
  resiResult.value = null
  polyPoints.value = []
  polyResult.value = null
  status.value = '就绪'
}

let pickListenerRef = ref(null)
let drawDblRef = ref(null)
function exitPick() {
  picking.value = false
  setPickMode(false)
  const container = store.map?.getContainer()
  if (pickListenerRef.value && container) {
    container.removeEventListener('click', pickListenerRef.value, true)
    pickListenerRef.value = null
  }
  if (drawDblRef.value && container) {
    container.removeEventListener('dblclick', drawDblRef.value, true)
    drawDblRef.value = null
  }
}

// 切换子页签时清理所有交互模式 (绘制/选点), 防止监听器残留
function cleanupModes() {
  exitPick()
  drawMode.value = false
  picking.value = false
  pickFor.value = null
}
onBeforeUnmount(exitPick)
updateLegend()
</script>

<template>
  <div class="pop-view">
    <aside class="panel">
      <div class="title">人口分析</div>

      <div class="sub-tabs">
        <button :class="['sub-tab', { active: subtab === 'density' }]" @click="subtab = 'density'; cleanupModes()">密度底图</button>
        <button :class="['sub-tab', { active: subtab === 'stat' }]" @click="subtab = 'stat'; cleanupModes()">区域统计</button>
        <button :class="['sub-tab', { active: subtab === 'grid' }]" @click="subtab = 'grid'; cleanupModes()">网格人口</button>
        <button :class="['sub-tab', { active: subtab === 'residential' }]" @click="subtab = 'residential'; cleanupModes()">小区分布</button>
      </div>

      <!-- 密度底图 -->
      <template v-if="subtab === 'density'">
        <div class="row">
          <button class="btn primary grow" @click="toggle">
            {{ enabled ? '关闭人口密度图层' : '开启人口密度图层' }}
          </button>
        </div>
        <div class="row">
          <span class="lbl">透明度</span>
          <input type="range" min="0.1" max="1" step="0.05" v-model.number="store.popOpacity" class="grow" />
          <span class="val">{{ Math.round(store.popOpacity * 100) }}%</span>
        </div>
        <div class="row">
          <button class="btn grow" @click="fitHefei">定位合肥全域</button>
        </div>
        <div class="hint">预渲染 100m 栅格底图，任意缩放直接可用。</div>
      </template>

      <!-- 区域统计 -->
      <template v-if="subtab === 'stat'">
        <div class="row">
          <button class="btn grow" :class="{ active: drawMode }" @click="drawMode ? stopDraw() : startDraw()">
            {{ drawMode ? '绘制中…(双击结束)' : '手绘多边形' }}
          </button>
          <button class="btn" v-if="polyPoints.length" @click="clearPolygon">清多边形</button>
        </div>
        <div class="hint" v-if="drawMode">点击地图添加顶点，双击结束。当前 {{ polyPoints.length }} 个顶点。</div>
        <div class="hint" v-else-if="polyPoints.length >= 3">已绘制 {{ polyPoints.length }} 边形，点「统计区域人口」。</div>
        <div class="row">
          <span class="lbl">中心</span>
          <input type="text" class="grow" readonly
                 :value="centerLat.toFixed(5) + ', ' + centerLng.toFixed(5)" />
          <button class="btn" :class="{ active: picking }" @click="picking ? exitPick() : pickCenter()">选点</button>
        </div>
        <div class="row">
          <span class="lbl">半径</span>
          <input type="range" min="0.5" max="8" step="0.5" v-model.number="radiusKm" class="grow" />
          <span class="val">{{ radiusKm }} km</span>
        </div>
        <div class="row">
          <button class="btn primary grow" @click="runStat">统计区域人口</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div class="stats" v-if="statResult">
          <div class="stat"><span>总人口</span><b>{{ statResult.population.toLocaleString() }}</b></div>
          <div class="stat"><span>面积</span><b>{{ statResult.area_km2 }} km²</b></div>
          <div class="stat"><span>密度</span><b>{{ statResult.density_per_km2.toLocaleString() }}/km²</b></div>
          <div class="stat"><span>小区数</span><b>{{ statResult.residential_count }}</b></div>
          <div class="stat"><span>人口格点</span><b>{{ statResult.pop_grid_points.toLocaleString() }}</b></div>
          <div class="stat"><span>单格均值</span><b>{{ statResult.avg_cell_population }}</b></div>
        </div>
        <div class="hint">统计中心半径范围内的总人口/密度/小区数（100m 栅格）。</div>
      </template>

      <!-- 网格人口 -->
      <template v-if="subtab === 'grid'">
        <div class="row">
          <span class="lbl">中心</span>
          <input type="text" class="grow" readonly
                 :value="centerLat.toFixed(5) + ', ' + centerLng.toFixed(5)" />
          <button class="btn" :class="{ active: picking }" @click="picking ? exitPick() : pickCenter()">选点</button>
        </div>
        <div class="row">
          <span class="lbl">半径</span>
          <input type="range" min="0.5" max="8" step="0.5" v-model.number="radiusKm" class="grow" />
          <span class="val">{{ radiusKm }} km</span>
        </div>
        <div class="row">
          <span class="lbl">网格</span>
          <div class="presets">
            <button v-for="s in [{v:0.002,l:'200m'},{v:0.005,l:'500m'},{v:0.01,l:'1km'}]"
                    :key="s.v" :class="['preset', { active: gridSize === s.v }]"
                    @click="gridSize = s.v">{{ s.l }}</button>
          </div>
        </div>
        <div class="row">
          <button class="btn primary grow" @click="runGridPop">生成人口网格</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div class="hint">网格人口密度 choropleth（色阶同人口密度底图）。</div>
      </template>

      <!-- 小区分布 -->
      <template v-if="subtab === 'residential'">
        <div class="row">
          <span class="lbl">中心</span>
          <input type="text" class="grow" readonly
                 :value="centerLat.toFixed(5) + ', ' + centerLng.toFixed(5)" />
          <button class="btn" :class="{ active: picking }" @click="picking ? exitPick() : pickCenter()">选点</button>
        </div>
        <div class="row">
          <span class="lbl">半径</span>
          <input type="range" min="0.5" max="8" step="0.5" v-model.number="radiusKm" class="grow" />
          <span class="val">{{ radiusKm }} km</span>
        </div>
        <div class="row">
          <button class="btn primary grow" @click="runResidential">加载小区人口</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div class="stats" v-if="resiResult">
          <div class="stat"><span>小区数</span><b>{{ resiResult.n_residential }}</b></div>
          <div class="stat"><span>估算总人口</span><b>{{ resiResult.estimated_total_population.toLocaleString() }}</b></div>
        </div>
        <div class="hint">小区人口为估算（按挂接节点聚合 100m 人口格，供热力/对比）。</div>
      </template>

      <div id="pop-legend" class="legend"></div>
    </aside>
    <div id="status">{{ status }}</div>
  </div>
</template>

<style scoped>
.pop-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; left: 12px; z-index: 1000; width: 290px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px;
  pointer-events: auto; max-height: calc(100vh - 80px); overflow-y: auto;
}
.title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.sub-tabs { display: flex; gap: 4px; margin-bottom: 10px; flex-wrap: wrap; }
.sub-tab {
  flex: 1; border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 7px; padding: 5px 0; font-size: 12px; cursor: pointer; min-width: 58px;
}
.sub-tab.active { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.row .lbl { color: var(--text-2); font-size: 12px; width: 32px; flex-shrink: 0; }
.row .val { font-size: 12px; color: var(--primary-dark); font-weight: 600; width: 46px; text-align: right; flex-shrink: 0; }
.grow { flex: 1; min-width: 0; }
.presets { display: flex; gap: 4px; flex: 1; }
.preset {
  flex: 1; border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 6px; padding: 3px 0; font-size: 11.5px; cursor: pointer; white-space: nowrap;
}
.preset:hover { border-color: var(--primary); color: var(--primary); }
.preset.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn { border: 1px solid var(--border); background: #fff; color: var(--text); padding: 6px 10px; border-radius: 8px; font-size: 12.5px; cursor: pointer; }
.btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); color: #fff; }
.btn.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.stats { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.stat {
  flex: 1 1 40%; border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px;
  display: flex; flex-direction: column; gap: 2px; text-align: center;
}
.stat span { font-size: 11px; color: var(--text-3); }
.stat b { font-size: 13px; color: var(--primary-dark); }
.legend { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-top: 10px; }
.hint { color: var(--text-3); font-size: 11.5px; line-height: 1.7; }
#status {
  position: fixed; left: 12px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 55%;
}
</style>

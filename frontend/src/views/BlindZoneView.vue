<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import L from 'leaflet'
import { api } from '../api'
import { store } from '../store'
import { clearOverlays, addGeoJson, setPickMode, addOverlay, clearCurrentPoint } from '../mapLayers'

const status = ref('就绪')
const category = ref('hospital')
const mode = ref('walk')
const timeBudget = ref(15)
const radiusKm = ref(6)
const centerLat = ref(store.pointLat)
const centerLng = ref(store.pointLng)
const picking = ref(false)
const meta = ref(null)
const loading = ref(false)

const CATS = [
  { v: 'hospital', l: '医院' }, { v: 'supermarket', l: '超市' }, { v: 'pharmacy', l: '药店' },
  { v: 'park', l: '公园' }, { v: 'mall', l: '商场' }, { v: 'market_food', l: '农贸' },
  { v: 'school_primary', l: '小学' }, { v: 'kindergarten', l: '幼儿园' },
  { v: 'school_junior', l: '初中' }, { v: 'school_senior', l: '高中' },
  { v: 'library', l: '图书馆' }, { v: 'culture', l: '文化场馆' },
  { v: 'elderly_care', l: '养老' }, { v: 'government', l: '政务' },
  { v: 'bank', l: '银行' }, { v: 'sports', l: '体育' }, { v: 'street_commercial', l: '商业街' },
]
const TIME_PRESETS = [5, 10, 15, 30]
const MODES = [
  { v: 'walk', l: '步行' },
  { v: 'cycle', l: '骑行' },
  { v: 'drive', l: '驾车' },
  { v: 'metro', l: '步行+地铁' },
  { v: 'bus', l: '步行+公交' },
  { v: 'walk+metro+bus', l: '步行+地铁+公交' },
]

function currentBBox() {
  const dLat = radiusKm.value / 111.32
  const dLng = radiusKm.value / (111.32 * Math.cos((centerLat.value * Math.PI) / 180))
  return [centerLng.value - dLng, centerLat.value - dLat, centerLng.value + dLng, centerLat.value + dLat]
}

async function loadBlindZone() {
  if (loading.value) return
  loading.value = true
  const bbox = currentBBox()
  status.value = `计算 ${CATS.find((c) => c.v === category.value)?.l || category.value} ${timeBudget.value}min 盲区…`
  const r = await api.blindzone(category.value, mode.value, timeBudget.value, bbox, 0.001, 'square', true, 15000)
  loading.value = false
  if (!r.ok) { status.value = `盲区分析失败: ${r.data.error || r.status}`; return }
  render(r.data)
  meta.value = r.data.meta
  status.value = `覆盖率 ${(r.data.meta.coverage_rate * 100).toFixed(1)}% | 盲区人口 ${r.data.meta.blind_population.toLocaleString()} | ${r.data.meta.n_cells} 个栅格点`
}

const TIER_STYLE = {
  '充裕': { color: '#1a9850', opacity: 0.5, label: '已覆盖', lblColor: '#1a9850' },
  '紧张': { color: '#f9a825', opacity: 0.85, label: '紧张可达', lblColor: '#f9a825' },
  '盲区': { color: '#d73027', opacity: 0.9, label: '盲区', lblColor: '#d73027' },
}

function render(fc) {
  clearOverlays()
  // 中心点标记 (纳入 overlays, 清空可移除)
  if (store.map) {
    const centerMk = L.circleMarker([centerLat.value, centerLng.value], {
      radius: 7, color: '#0d47a1', weight: 2.5, fillColor: '#1976d2', fillOpacity: 0.9,
    }).bindPopup(
      `<div class="pop-pop"><div class="pp-title">分析中心</div>` +
      `${centerLat.value.toFixed(5)}, ${centerLng.value.toFixed(5)}</div>`)
    addOverlay(centerMk)
  }
  // 该类别 POI 设施点 (可点击查看详情)
  const facs = fc.facilities || []
  if (facs.length) {
    const fl = L.geoJSON({
      type: 'FeatureCollection',
      features: facs.map((f) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [f.lng, f.lat] },
        properties: f,
      })),
    }, {
      pointToLayer: (f, ll) => L.circleMarker(ll, {
        radius: 6, color: '#fff', weight: 1.5, fillColor: '#e65100', fillOpacity: 0.95,
      }),
    })
    fl.eachLayer((ly) => {
      const p = ly.feature.properties
      ly.bindPopup(
        `<div class="pop-pop"><div class="pp-title">${p.name || '(未命名)'}</div>` +
        `${p.address ? `地址 <b>${p.address}</b><br/>` : ''}` +
        `${p.rating ? `评分 <b>${p.rating}</b><br/>` : ''}` +
        `${p.opentime_today ? `营业 <b>${p.opentime_today}</b><br/>` : ''}` +
        `类型 <b>${p.sub_category || p.category || ''}</b></div>`,
        { maxWidth: 300 })
    })
    addOverlay(fl)
  }
  // 100m 人口栅格点: 盲区=红, 紧张=黄, 覆盖=绿
  const pts = addGeoJson(fc, (f) => {
    const p = f.properties
    const st = TIER_STYLE[p.tier] || TIER_STYLE[p.blind ? '盲区' : '充裕']
    return {
      color: 'rgba(0,0,0,0.0)', weight: 0,
      fillColor: st.color, fillOpacity: st.opacity,
    }
  }, { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3 }) })
  pts.eachLayer((ly) => {
    const p = ly.feature.properties
    const st = TIER_STYLE[p.tier] || TIER_STYLE[p.blind ? '盲区' : '充裕']
    ly.bindPopup(
      `<div class="pop-pop"><div class="pp-title">100m 人口栅格点</div>` +
      `人口 <b>${p.population.toLocaleString()}</b><br/>` +
      `状态 <b style="color:${st.lblColor}">${st.label}</b></div>`,
      { maxWidth: 240 })
  })
  updateLegend()
}

function onClear() {
  clearOverlays()
  clearCurrentPoint()
  meta.value = null
  status.value = '就绪'
  const legend = document.getElementById('blind-legend')
  if (legend) legend.innerHTML = ''
}

function updateLegend() {
  const legend = document.getElementById('blind-legend')
  if (!legend) return
  legend.innerHTML =
    `<div class="lrow"><span class="swatch" style="background:#d73027"></span><span class="ltxt">盲区（阈值内到不了设施）</span></div>` +
    `<div class="lrow"><span class="swatch" style="background:#f9a825"></span><span class="ltxt">紧张（可达但时间紧）</span></div>` +
    `<div class="lrow"><span class="swatch" style="background:#1a9850;opacity:.5"></span><span class="ltxt">已覆盖（充裕）</span></div>`
}

let pickListener = null
function startPick() {
  picking.value = true
  setPickMode(true)
  status.value = '选点模式：点击地图选择中心点'
  const container = store.map.getContainer()
  pickListener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation()
    e.preventDefault()
    const ll = store.map.mouseEventToLatLng(e)
    exitPick()
    if (ll) {
      centerLat.value = +ll.lat.toFixed(6)
      centerLng.value = +ll.lng.toFixed(6)
      status.value = `中心点已设为 ${centerLat.value.toFixed(5)}, ${centerLng.value.toFixed(5)}，点「生成」计算`
    }
  }
  container.addEventListener('click', pickListener, true)
}
function exitPick() {
  picking.value = false
  setPickMode(false)
  if (pickListener) {
    store.map.getContainer().removeEventListener('click', pickListener, true)
    pickListener = null
  }
}
onBeforeUnmount(exitPick)
onMounted(updateLegend)
watch([category, mode, timeBudget, radiusKm, centerLat, centerLng], () => { if (meta.value) loadBlindZone() })
</script>

<template>
  <div class="blindzone-view">
    <aside class="panel">
      <div class="title">服务盲区识别</div>

      <div class="row">
        <span class="lbl">中心点</span>
        <input type="text" class="grow" readonly
               :value="centerLat.toFixed(5) + ', ' + centerLng.toFixed(5)" />
        <button class="btn" :class="{ active: picking }" @click="picking ? exitPick() : startPick()">
          {{ picking ? '选点中…' : '选点' }}
        </button>
      </div>
      <div class="row">
        <span class="lbl">半径</span>
        <input type="range" min="1" max="20" step="0.5" v-model.number="radiusKm" class="grow" />
        <span class="val">{{ radiusKm }} km</span>
      </div>
      <div class="row">
        <span class="lbl">类别</span>
        <select v-model="category" class="grow">
          <option v-for="c in CATS" :key="c.v" :value="c.v">{{ c.l }}</option>
        </select>
      </div>
      <div class="row">
        <span class="lbl">阈值</span>
        <div class="presets">
          <button v-for="t in TIME_PRESETS" :key="t"
                  :class="['preset', { active: timeBudget === t }]"
                  @click="timeBudget = t">{{ t }}min</button>
        </div>
      </div>
      <div class="row">
        <span class="lbl">模式</span>
        <select v-model="mode" class="grow">
          <option v-for="m in MODES" :key="m.v" :value="m.v">{{ m.l }}</option>
        </select>
      </div>
      <div class="row">
        <button class="btn primary grow" @click="loadBlindZone">生成盲区</button>
        <button class="btn" @click="onClear">清空</button>
      </div>

      <div class="stats" v-if="meta">
        <div class="stat"><span>范围覆盖率</span><b>{{ (meta.coverage_rate * 100).toFixed(1) }}%</b></div>
        <div class="stat"><span>范围人口</span><b>{{ meta.cells_population.toLocaleString() }}</b></div>
        <div class="stat"><span>盲区人口</span><b class="warn">{{ meta.blind_population.toLocaleString() }}</b></div>
      </div>

      <div id="blind-legend" class="legend"></div>
      <div class="hint">
        红点 = 盲区（阈值内到不了任何该设施）；黄点 = 紧张（可达但耗时≥阈值 70%）；绿点 = 已覆盖。<br />
        橙色圆点 = 该类别设施（可点击查看名称/地址/评分）；蓝色圆点 = 分析中心。<br />
        步行阈值：5min≈417m、10min≈833m、15min≈1.25km。<br />
        100m 分辨率人口栅格，采样最多 1.5 万点。
      </div>
    </aside>
    <div id="status">{{ status }}</div>
  </div>
</template>

<style scoped>
.blindzone-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; left: 12px; z-index: 1000; width: 284px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px;
  pointer-events: auto;
  max-height: calc(100vh - 80px); overflow-y: auto;
}
.title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.row { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; }
.row .lbl { color: var(--text-2); font-size: 12px; width: 32px; flex-shrink: 0; }
.row .val { font-size: 12px; color: var(--primary-dark); font-weight: 600; width: 46px; text-align: right; flex-shrink: 0; }
.grow { flex: 1; min-width: 0; }
.presets { display: flex; gap: 4px; flex: 1; }
.preset {
  flex: 1; border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 6px; padding: 3px 0; font-size: 11.5px; cursor: pointer;
  white-space: nowrap;
}
.preset:hover { border-color: var(--primary); color: var(--primary); }
.preset.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.stats { display: flex; gap: 8px; margin-bottom: 10px; }
.stat {
  flex: 1; border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px;
  display: flex; flex-direction: column; gap: 2px; text-align: center;
}
.stat span { font-size: 11px; color: var(--text-3); }
.stat b { font-size: 14px; color: var(--primary-dark); }
.stat b.warn { color: #d32f2f; }
.legend { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.hint { color: var(--text-3); font-size: 11.5px; line-height: 1.6; }
#status {
  position: fixed; left: 12px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 55%;
}
</style>

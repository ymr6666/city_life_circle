<script setup>
import { ref, watch, onMounted, onBeforeUnmount, computed } from 'vue'
import L from 'leaflet'
import { api } from '../api'
import { store } from '../store'
import { clearOverlays, addGeoJson, setPickMode, addOverlay, mismatchRamp } from '../mapLayers'
import ChartBox from '../components/ChartBox.vue'
import { coverageRateOption } from '../chartOptions'

const status = ref('就绪')
const subtab = ref('blind')      // blind / cluster / mismatch / balance
const category = ref('hospital')
const mode = ref('walk')
const timeBudget = ref(15)
const radiusKm = ref(6)
const centerLat = ref(store.pointLat)
const centerLng = ref(store.pointLng)
const picking = ref(false)
const loading = ref(false)
const tier = ref(null)

// 各子页签数据
const meta = ref(null)            // 盲区识别
const clusterData = ref(null)     // 盲区聚类
const clusterActiveId = ref(null)
const clusterMinPts = ref(5)
const clusterTopN = ref(10)
const clusterCell = ref(0.0025)
const clusterConn = ref(4)
const mismatchData = ref(null)    // 错配分析
const mismatchCell = ref(0.001)
const balanceData = ref(null)     // 均衡分析

const TIERS = [
  { v: null, l: '全部' },
  { v: 3, l: '三甲/综合' },
  { v: 2, l: '+专科' },
  { v: 1, l: '基层/全部' },
]

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
const SUBTABS = [
  { v: 'blind', l: '盲区识别' },
  { v: 'cluster', l: '盲区聚类' },
  { v: 'mismatch', l: '错配分析' },
  { v: 'balance', l: '均衡分析' },
]
const catLabel = () => CATS.find((c) => c.v === category.value)?.l || category.value

function currentBBox() {
  const dLat = radiusKm.value / 111.32
  const dLng = radiusKm.value / (111.32 * Math.cos((centerLat.value * Math.PI) / 180))
  return [centerLng.value - dLng, centerLat.value - dLat, centerLng.value + dLng, centerLat.value + dLat]
}

// ---------- 通用: 中心点 ----------
function renderCenter() {
  if (store.map) {
    const mk = L.circleMarker([centerLat.value, centerLng.value], {
      radius: 7, color: '#0d47a1', weight: 2.5, fillColor: '#1976d2', fillOpacity: 0.9,
    }).bindPopup(
      `<div class="pop-pop"><div class="pp-title">分析中心</div>` +
      `${centerLat.value.toFixed(5)}, ${centerLng.value.toFixed(5)}</div>`)
    addOverlay(mk)
  }
}

// ---------- 盲区识别 ----------
async function loadBlindZone() {
  if (loading.value) return
  loading.value = true
  const bbox = currentBBox()
  status.value = `计算 ${catLabel()} ${timeBudget.value}min 盲区…`
  const r = await api.blindzone(category.value, mode.value, timeBudget.value, bbox, 0.001, 'square', true, 15000, tier.value)
  loading.value = false
  if (!r.ok) { status.value = `盲区分析失败: ${r.data.error || r.status}`; return }
  renderBlind(r.data)
  meta.value = r.data.meta
  status.value = `覆盖率 ${(r.data.meta.coverage_rate * 100).toFixed(1)}% | 盲区人口 ${r.data.meta.blind_population.toLocaleString()} | ${r.data.meta.n_cells} 个栅格点`
}

const TIER_STYLE = {
  '充裕': { color: '#1a9850', opacity: 0.5, label: '已覆盖', lblColor: '#1a9850' },
  '紧张': { color: '#f9a825', opacity: 0.85, label: '紧张可达', lblColor: '#f9a825' },
  '盲区': { color: '#d73027', opacity: 0.9, label: '盲区', lblColor: '#d73027' },
}

function renderBlind(fc) {
  clearOverlays()
  renderCenter()
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
  const pts = addGeoJson(fc, (f) => {
    const p = f.properties
    const st = TIER_STYLE[p.tier] || TIER_STYLE[p.blind ? '盲区' : '充裕']
    return { color: 'rgba(0,0,0,0.0)', weight: 0, fillColor: st.color, fillOpacity: st.opacity }
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

// ---------- 盲区聚类 ----------
const CLUSTER_COLORS = ['#d73027', '#f57c00', '#8e24aa', '#e53935', '#6d4c41', '#5e35b1', '#c62828', '#ad1457']
async function loadClusters() {
  if (loading.value) return
  loading.value = true
  const bbox = currentBBox()
  status.value = `聚类 ${catLabel()} ${timeBudget.value}min 盲区…`
  const r = await api.citywideClusters(category.value, mode.value, timeBudget.value, bbox, tier.value, clusterCell.value, clusterMinPts.value, clusterTopN.value, clusterConn.value)
  loading.value = false
  if (!r.ok) { status.value = `聚类失败: ${r.data.error || r.status}`; return }
  clusterData.value = r.data
  clusterActiveId.value = null
  renderClusters()
  status.value = `识别 ${r.data.meta.n_clusters} 个连续盲区 | 盲区人口 ${r.data.meta.blind_population.toLocaleString()}`
}

function renderClusters() {
  clearOverlays()
  renderCenter()
  const d = clusterData.value
  if (!d) return
  // 盲区底图点
  if (d.features && d.features.features && d.features.features.length) {
    addGeoJson(d.features, () => ({ color: 'rgba(0,0,0,0.0)', weight: 0, fillColor: '#d73027', fillOpacity: 0.55 }),
      { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 2.5 }) })
  }
  // 聚类多边形
  ;(d.clusters || []).forEach((cl) => {
    if (!cl.polygon) return
    const isActive = cl.id === clusterActiveId.value
    const color = isActive ? '#c62828' : CLUSTER_COLORS[(cl.id - 1) % CLUSTER_COLORS.length]
    const poly = addGeoJson({ type: 'Feature', geometry: cl.polygon, properties: cl }, {
      color: isActive ? '#c62828' : color, weight: isActive ? 3 : 2,
      fillColor: color, fillOpacity: isActive ? 0.55 : 0.30,
    })
    poly.eachLayer((ly) => {
      const p = ly.feature.properties
      ly.bindPopup(
        `<div class="pop-pop"><div class="pp-title">盲区簇 #${p.id}</div>` +
        `盲区人口 <b>${p.population.toLocaleString()}</b><br/>` +
        `栅格点 <b>${p.n_points}</b> 个<br/>` +
        `中心 <b>${p.centroid.lat.toFixed(4)}, ${p.centroid.lng.toFixed(4)}</b></div>`,
        { maxWidth: 260 })
      ly.on('click', () => selectCluster(cl.id))
    })
    // 中心圆点 (可点击定位)
    const mk = L.circleMarker([cl.centroid.lat, cl.centroid.lng], {
      radius: 6, color: '#fff', weight: 1.5, fillColor: color, fillOpacity: 0.95,
    }).bindPopup(
      `<div class="pop-pop"><div class="pp-title">盲区簇 #${cl.id}</div>` +
      `盲区人口 <b>${cl.population.toLocaleString()}</b></div>`, { maxWidth: 240 })
    mk.on('click', () => selectCluster(cl.id))
    addOverlay(mk)
  })
  updateLegend()
}

function selectCluster(id) {
  clusterActiveId.value = id
  renderClusters()
  const cl = (clusterData.value?.clusters || []).find((c) => c.id === id)
  if (cl && store.map) store.map.setView([cl.centroid.lat, cl.centroid.lng], Math.max(store.map.getZoom(), 12))
  status.value = `盲区簇 #${id}：人口 ${cl ? cl.population.toLocaleString() : ''}`
}

// ---------- 错配分析 ----------
async function loadMismatch() {
  if (loading.value) return
  loading.value = true
  const bbox = currentBBox()
  status.value = `错配分析 ${catLabel()}…`
  const r = await api.citywideMismatch(category.value, bbox, tier.value, mismatchCell.value, 'hex')
  loading.value = false
  if (!r.ok) { status.value = `错配分析失败: ${r.data.error || r.status}`; return }
  mismatchData.value = r.data
  renderMismatch()
  status.value = `错配网格 ${r.data.meta.n_cells} 格 | 红=高人口低设施(缺口) 绿=均衡 蓝=设施冗余`
}

function renderMismatch() {
  clearOverlays()
  renderCenter()
  const d = mismatchData.value
  if (!d) return
  const grid = addGeoJson(d, (f) => {
    const m = f.properties.mismatch || 0
    return { color: 'rgba(0,0,0,0.12)', weight: 0.6, fillColor: mismatchRamp(m), fillOpacity: 0.85 }
  })
  grid.eachLayer((ly) => {
    const p = ly.feature.properties
    ly.bindPopup(
      `<div class="pop-pop"><div class="pp-title">错配格</div>` +
      `人口 <b>${p.population.toLocaleString()}</b><br/>` +
      `设施 <b>${p.fac_count}</b> 个<br/>` +
      `每万人设施 <b>${p.fac_per_10k}</b><br/>` +
      `错配指数 <b style="color:${mismatchRamp(p.mismatch)}">${p.mismatch}</b>` +
      `（>0 缺口 / <0 冗余）</div>`, { maxWidth: 260 })
  })
  updateLegend()
}

// ---------- 均衡分析 ----------
async function loadBalance() {
  if (loading.value) return
  loading.value = true
  status.value = `计算 ${catLabel()} 全城均衡指标…`
  const r = await api.citywideBalance(category.value, mode.value, timeBudget.value, null, tier.value)
  loading.value = false
  if (!r.ok) { status.value = `均衡分析失败: ${r.data.error || r.status}`; return }
  balanceData.value = r.data
  clearOverlays()
  renderCenter()
  status.value = `覆盖率 ${(r.data.coverage_rate * 100).toFixed(1)}% | 盲区人口 ${r.data.blind_population.toLocaleString()} | 每万人设施 ${r.data.facility_per_10k}`
}

const balanceBarOption = computed(() => {
  const d = balanceData.value
  if (!d || !d.coverage_by_time || !d.coverage_by_time.length) return null
  return coverageRateOption({ items: d.coverage_by_time })
})

// ---------- 图例 ----------
function updateLegend() {
  const legend = document.getElementById('cw-legend')
  if (!legend) return
  const html = {
    blind: `<div class="lrow"><span class="swatch" style="background:#d73027"></span><span class="ltxt">盲区（阈值内到不了设施）</span></div>` +
           `<div class="lrow"><span class="swatch" style="background:#f9a825"></span><span class="ltxt">紧张（可达但时间紧）</span></div>` +
           `<div class="lrow"><span class="swatch" style="background:#1a9850;opacity:.5"></span><span class="ltxt">已覆盖（充裕）</span></div>`,
    cluster: `<div class="lrow"><span class="swatch" style="background:#d73027"></span><span class="ltxt">盲区底图点</span></div>` +
             `<div class="lrow"><span class="swatch" style="background:#f57c00"></span><span class="ltxt">连续盲区簇（点击查看/定位）</span></div>`,
    mismatch: `<div class="lrow"><span class="swatch" style="background:#d73027"></span><span class="ltxt">高人口低设施（缺口）</span></div>` +
              `<div class="lrow"><span class="swatch" style="background:#66bd63"></span><span class="ltxt">均衡</span></div>` +
              `<div class="lrow"><span class="swatch" style="background:#4575b4"></span><span class="ltxt">设施冗余（低人口高设施）</span></div>`,
    balance: '',
  }
  legend.innerHTML = html[subtab.value] || ''
}

// ---------- 清空 / 选点 ----------
function onClear() {
  clearOverlays()
  meta.value = null
  clusterData.value = null
  clusterActiveId.value = null
  mismatchData.value = null
  balanceData.value = null
  status.value = '就绪'
  updateLegend()
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
      status.value = `中心点已设为 ${centerLat.value.toFixed(5)}, ${centerLng.value.toFixed(5)}`
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

watch([category, mode, timeBudget, radiusKm, centerLat, centerLng, tier, clusterCell, clusterConn], () => {
  if (subtab.value === 'blind' && meta.value) loadBlindZone()
  else if (subtab.value === 'cluster' && clusterData.value) loadClusters()
  else if (subtab.value === 'mismatch' && mismatchData.value) loadMismatch()
  else if (subtab.value === 'balance' && balanceData.value) loadBalance()
})
function switchSubtab(v) {
  subtab.value = v
  updateLegend()
  status.value = '就绪'
}
function fmtN(v) { return (v || 0).toLocaleString() }
</script>

<template>
  <div class="blindzone-view">
    <aside class="panel">
      <div class="title">全城分析</div>

      <div class="sub-tabs">
        <button v-for="s in SUBTABS" :key="s.v"
                :class="['sub-tab', { active: subtab === s.v }]"
                @click="switchSubtab(s.v)">{{ s.l }}</button>
      </div>

      <!-- 公共参数 -->
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
      <div class="row" v-if="category === 'hospital'">
        <span class="lbl">等级</span>
        <div class="presets">
          <button v-for="t in TIERS" :key="String(t.v)"
                  :class="['preset', { active: tier === t.v }]"
                  @click="tier = t.v">{{ t.l }}</button>
        </div>
      </div>

      <!-- 盲区识别 -->
      <template v-if="subtab === 'blind'">
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
          <div class="stat"><span>范围人口</span><b>{{ fmtN(meta.cells_population) }}</b></div>
          <div class="stat"><span>盲区人口</span><b class="warn">{{ fmtN(meta.blind_population) }}</b></div>
        </div>
      </template>

      <!-- 盲区聚类 -->
      <template v-if="subtab === 'cluster'">
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
          <span class="lbl">最小点</span>
          <input type="number" min="1" max="100" v-model.number="clusterMinPts" class="grow" />
        </div>
        <div class="row">
          <span class="lbl">前 N</span>
          <input type="number" min="1" max="50" v-model.number="clusterTopN" class="grow" />
        </div>
        <div class="row">
          <span class="lbl">格网</span>
          <input type="number" min="0.001" max="0.01" step="0.0005" v-model.number="clusterCell" class="grow" />
          <span class="val">{{ Math.round(clusterCell * 1000) }}m</span>
        </div>
        <div class="row">
          <span class="lbl">连通</span>
          <div class="presets">
            <button :class="['preset', { active: clusterConn === 4 }]" @click="clusterConn = 4">4邻域</button>
            <button :class="['preset', { active: clusterConn === 8 }]" @click="clusterConn = 8">8邻域</button>
          </div>
        </div>
        <div class="row">
          <button class="btn primary grow" @click="loadClusters">识别盲区簇</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div class="cluster-list" v-if="clusterData && clusterData.clusters.length">
          <div v-for="cl in clusterData.clusters" :key="cl.id"
               :class="['c-item', { active: cl.id === clusterActiveId }]"
               @click="selectCluster(cl.id)">
            <span class="c-rank" :style="{ background: CLUSTER_COLORS[(cl.id - 1) % CLUSTER_COLORS.length] }">{{ cl.id }}</span>
            <div class="c-main">
              <div class="c-name">盲区簇 #{{ cl.id }}</div>
              <div class="c-meta">人口 {{ fmtN(cl.population) }} · {{ cl.n_points }} 格点</div>
            </div>
          </div>
        </div>
      </template>

      <!-- 错配分析 -->
      <template v-if="subtab === 'mismatch'">
        <div class="row">
          <span class="lbl">格网</span>
          <input type="number" min="0.0005" max="0.02" step="0.0005" v-model.number="mismatchCell" class="grow" />
          <span class="val">{{ mismatchCell >= 0.01 ? Math.round(mismatchCell * 100) + 'km' : Math.round(mismatchCell * 1000) + 'm' }}</span>
        </div>
        <div class="row">
          <button class="btn primary grow" @click="loadMismatch">生成错配图</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div class="stats" v-if="mismatchData">
          <div class="stat"><span>网格数</span><b>{{ mismatchData.meta.n_cells }}</b></div>
          <div class="stat"><span>均人口/格</span><b>{{ Math.round(mismatchData.meta.mean_pop).toLocaleString() }}</b></div>
          <div class="stat"><span>均设施/格</span><b>{{ mismatchData.meta.mean_fac }}</b></div>
        </div>
      </template>

      <!-- 均衡分析 -->
      <template v-if="subtab === 'balance'">
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
          <button class="btn primary grow" @click="loadBalance">计算全城均衡</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div v-if="balanceData" class="bal-cards">
          <div class="b-card"><span>全城覆盖率</span><b>{{ (balanceData.coverage_rate * 100).toFixed(1) }}%</b></div>
          <div class="b-card"><span>盲区人口</span><b class="warn">{{ fmtN(balanceData.blind_population) }}</b></div>
          <div class="b-card"><span>设施总数</span><b>{{ balanceData.facility_count }}</b></div>
          <div class="b-card"><span>每万人设施</span><b>{{ balanceData.facility_per_10k }}</b></div>
          <div class="b-card"><span>人口/设施</span><b>{{ balanceData.population_per_facility ?? '—' }}</b></div>
          <div class="b-card"><span>最近设施中位数</span><b>{{ balanceData.distance_minutes.p50 ?? '—' }}min</b></div>
          <div class="b-card"><span>p75</span><b>{{ balanceData.distance_minutes.p75 ?? '—' }}min</b></div>
          <div class="b-card"><span>p90</span><b>{{ balanceData.distance_minutes.p90 ?? '—' }}min</b></div>
        </div>
        <ChartBox v-if="balanceBarOption" :option="balanceBarOption" height="170px" />
      </template>

      <div id="cw-legend" class="legend"></div>
      <div class="hint">
        盲区识别：红/黄/绿 = 盲区 / 紧张 / 覆盖；聚类：粗网格连通域 + 凹包贴合点云（4邻域=共享边才连通，8邻域合并更激进）；<br />
        错配：z 分数差（人口 vs 设施），红=高人口低设施缺口；均衡：全城供需宏观指标。<br />
        100m 人口栅格，采样最多 1.5 万点。
      </div>
    </aside>
    <div id="status">{{ status }}</div>
  </div>
</template>

<style scoped>
.blindzone-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; left: 12px; z-index: 1000; width: 300px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px;
  pointer-events: auto;
  max-height: calc(100vh - 80px); overflow-y: auto;
}
.title { font-weight: 600; font-size: 14px; margin-bottom: 8px; }
.sub-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
.sub-tab {
  flex: 1; border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 7px; padding: 5px 0; font-size: 12px; cursor: pointer; white-space: nowrap;
}
.sub-tab.active { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.row { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; }
.row .lbl { color: var(--text-2); font-size: 12px; width: 32px; flex-shrink: 0; }
.row .val { font-size: 12px; color: var(--primary-dark); font-weight: 600; width: 52px; text-align: right; flex-shrink: 0; }
.grow { flex: 1; min-width: 0; }
.presets { display: flex; gap: 4px; flex: 1; }
.preset {
  flex: 1; border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 6px; padding: 3px 0; font-size: 11.5px; cursor: pointer;
  white-space: nowrap;
}
.preset:hover { border-color: var(--primary); color: var(--primary); }
.preset.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn { border: 1px solid var(--border); background: #fff; color: var(--text); padding: 5px 10px; border-radius: 8px; font-size: 12.5px; cursor: pointer; }
.btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); color: #fff; }
.btn.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.stats { display: flex; gap: 6px; margin: 8px 0; }
.stat {
  flex: 1; border: 1px solid var(--border); border-radius: 8px; padding: 6px 6px;
  display: flex; flex-direction: column; gap: 2px; text-align: center;
}
.stat span { font-size: 11px; color: var(--text-3); }
.stat b { font-size: 13px; color: var(--primary-dark); }
.stat b.warn { color: #d32f2f; }
.legend { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin: 8px 0; }
.lrow { display: flex; align-items: center; gap: 7px; padding: 2px 0; }
.swatch { width: 14px; height: 10px; border-radius: 2px; flex-shrink: 0; }
.ltxt { font-size: 11.5px; color: var(--text-2); }
.cluster-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; max-height: 190px; overflow-y: auto; }
.c-item { display: flex; gap: 7px; align-items: center; padding: 5px 8px; border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.c-item:hover { border-color: var(--primary); }
.c-item.active { border-color: #d32f2f; box-shadow: 0 0 0 2px rgba(211,47,47,.2); }
.c-rank { width: 18px; height: 18px; border-radius: 50%; color: #fff; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.c-main { flex: 1; min-width: 0; }
.c-name { font-size: 12px; font-weight: 600; }
.c-meta { font-size: 11px; color: var(--text-2); }
.bal-cards { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.b-card {
  flex: 1 1 42%; border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px;
  display: flex; flex-direction: column; gap: 2px; text-align: center;
}
.b-card span { font-size: 11px; color: var(--text-3); }
.b-card b { font-size: 14px; color: var(--primary-dark); }
.b-card b.warn { color: #d32f2f; }
.hint { color: var(--text-3); font-size: 11.5px; line-height: 1.6; }
#status {
  position: fixed; left: 12px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 55%;
}
</style>

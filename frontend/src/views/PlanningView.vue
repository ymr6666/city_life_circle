<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import L from 'leaflet'
import { api } from '../api'
import { store } from '../store'
import { clearOverlays, addOverlay, addGeoJson, setPickMode } from '../mapLayers'

const status = ref('就绪')
const subtab = ref('site')      // site / closure / relocation
const category = ref('hospital')
const mode = ref('walk')
const timeBudget = ref(15)
const radiusKm = ref(6)
const centerLat = ref(store.pointLat)
const centerLng = ref(store.pointLng)
const nCandidates = ref(8)
const picking = ref(false)
const pickFor = ref(null)
const loading = ref(false)
const result = ref(null)
const tier = ref(null)

const TIERS = [
  { v: null, l: '全部' },
  { v: 3, l: '三甲/综合' },
  { v: 2, l: '+专科' },
  { v: 1, l: '基层/全部' },
]

// 研究范围状态
const rangeLoaded = ref(false)
const rangeFacilities = ref([])     // 范围内该类设施 [{id,name,lng,lat,address}]
const rangeMeta = ref(null)         // 范围内覆盖情况
const rangeBlind = ref([])          // 盲区底图点 [{lng,lat,tier,population}]
const rangeCoverLayer = ref(null)   // 覆盖底图
const rangeRect = ref(null)         // 研究范围框
const rangeCenter = ref(false)      // 已渲染中心

// 关闭影响
const closeTargets = ref([])
const closeFallback = ref(30)

// 搬迁影响
const relocOld = ref(null)
const relocNew = ref(null)

// 选址
const extraCands = ref([])
const activeCandIdx = ref(-1)       // 当前高亮候选

const CATS = [
  { v: 'hospital', l: '医院' }, { v: 'supermarket', l: '超市' }, { v: 'pharmacy', l: '药店' },
  { v: 'park', l: '公园' }, { v: 'mall', l: '商场' }, { v: 'market_food', l: '农贸' },
  { v: 'school_primary', l: '小学' }, { v: 'kindergarten', l: '幼儿园' },
  { v: 'school_junior', l: '初中' }, { v: 'school_senior', l: '高中' },
  { v: 'library', l: '图书馆' }, { v: 'culture', l: '文化场馆' },
  { v: 'elderly_care', l: '养老' }, { v: 'government', l: '政务' },
  { v: 'bank', l: '银行' }, { v: 'sports', l: '体育' }, { v: 'street_commercial', l: '商业街' },
]
const MODES = [
  { v: 'walk', l: '步行' }, { v: 'cycle', l: '骑行' }, { v: 'drive', l: '驾车' },
  { v: 'metro', l: '步行+地铁' }, { v: 'bus', l: '步行+公交' },
  { v: 'walk+metro+bus', l: '步行+地铁+公交' },
]
const TIME_PRESETS = [5, 10, 15, 30]

function currentBBox() {
  const dLat = radiusKm.value / 111.32
  const dLng = radiusKm.value / (111.32 * Math.cos((centerLat.value * Math.PI) / 180))
  return [centerLng.value - dLng, centerLat.value - dLat, centerLng.value + dLng, centerLat.value + dLat]
}
const catLabel = () => CATS.find((c) => c.v === category.value)?.l || category.value

// ---------- 研究范围加载 ----------
async function loadRange() {
  loading.value = true
  status.value = `加载研究范围 ${catLabel()} ${timeBudget.value}min…`
  const bbox = currentBBox()
  const r = await api.blindzone(category.value, mode.value, timeBudget.value, bbox, 0.001, 'square', true, 3000, tier.value)
  loading.value = false
  if (!r.ok) { status.value = `加载失败: ${r.data.error || r.status}`; return }
  rangeFacilities.value = r.data.facilities || []
  rangeMeta.value = r.data.meta
  // 盲区底图点 (从 blindzone point mode 提取)
  rangeBlind.value = (r.data.features || []).map((f) => ({
    lng: f.geometry.coordinates[0], lat: f.geometry.coordinates[1],
    tier: f.properties.tier || (f.properties.blind ? '盲区' : '充裕'),
    population: f.properties.population || 0,
  }))
  rangeLoaded.value = true
  renderRange()
  status.value = `研究范围 ${radiusKm.value}km | ${rangeFacilities.value.length} 个${catLabel()} | 覆盖率 ${(r.data.meta.coverage_rate * 100).toFixed(1)}% | 盲区人口 ${r.data.meta.blind_population.toLocaleString()}`
}

function renderRange() {
  clearOverlays()
  renderRangeBase()   // 研究范围框
  addCenter()         // 研究中心点

  // 盲区底图参考点 (红=盲区/黄=紧张/绿=覆盖, 选址参考; 低透明度)
  const tierColor = { '充裕': '#1a9850', '紧张': '#fee08b', '盲区': '#d73027' }
  const blindFC = {
    type: 'FeatureCollection',
    features: rangeBlind.value.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
      properties: { tier: p.tier },
    })),
  }
  if (rangeBlind.value.length) {
    const bl = addGeoJson(blindFC, (f) => {
      const c = tierColor[f.properties.tier] || '#1a9850'
      return { color: 'rgba(0,0,0,0)', weight: 0, fillColor: c, fillOpacity: f.properties.tier === '盲区' ? 0.40 : 0.15 }
    }, { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3 }) })
    bl.eachLayer((ly) => {
      const p = ly.feature.properties
      ly.bindPopup(
        `<div class="pop-pop"><div class="pp-title">盲区参考</div>` +
        `状态 <b style="color:${tierColor[p.tier]}">${p.tier === '盲区' ? '盲区' : p.tier === '紧张' ? '紧张可达' : '已覆盖'}</b></div>`,
        { maxWidth: 200 })
    })
  }

  // 范围内设施点 (橙色, 可点击; 关闭/搬迁模式下点击即选中)
  rangeFacilities.value.forEach((f, i) => {
    const mk = L.circleMarker([f.lat, f.lng], {
      radius: 6, color: '#fff', weight: 1.5, fillColor: '#e65100', fillOpacity: 0.95,
    }).bindPopup(
      `<div class="pop-pop"><div class="pp-title">${f.name || '(未命名)'}</div>` +
      `${f.address ? `地址 <b>${f.address}</b><br/>` : ''}` +
      `${f.rating ? `评分 <b>${f.rating}</b><br/>` : ''}` +
      `类型 <b>${catLabel()}</b><br/>` +
      `(第 ${i + 1} 个, id=${f.id})</div>`, { maxWidth: 300 })
    mk.on('click', () => onFacilityClick(f))
    addOverlay(mk)
  })
}

// 设施点点击: 按当前子页签选择设施
function onFacilityClick(f) {
  if (subtab.value === 'closure') {
    toggleCloseTarget(f)
    status.value = closeTargets.value.some((x) => x.id === f.id)
      ? `已勾选 ${f.name} (${closeTargets.value.length} 个待评估)`
      : `已取消 ${f.name}`
  } else if (subtab.value === 'relocation') {
    selectRelocOld(f)
  } else {
    status.value = `设施 ${f.name} (第 ${rangeFacilities.value.indexOf(f) + 1} 个)`
  }
}

function renderRangeBase() {
  // 研究范围框由 renderRange 统一添加, 这里无需重复
  if (store.map) {
    addOverlay(L.rectangle(
      [[currentBBox()[1], currentBBox()[0]], [currentBBox()[3], currentBBox()[2]]],
      { color: '#1565c0', weight: 1.5, dashArray: '4,4', fill: false, opacity: 0.7 }))
  }
}

function addCenter() {
  if (store.map) {
    const mk = L.circleMarker([centerLat.value, centerLng.value], {
      radius: 6, color: '#0d47a1', weight: 2, fillColor: '#1976d2', fillOpacity: 0.9,
    }).bindPopup(`<div class="pop-pop"><div class="pp-title">研究中心</div>${centerLat.value.toFixed(5)}, ${centerLng.value.toFixed(5)}</div>`)
    addOverlay(mk)
  }
}

function pickCenter() {
  picking.value = true
  pickFor.value = 'center'
  setPickMode(true)
  status.value = '选点模式：点击地图设置研究中心'
  const container = store.map.getContainer()
  const listener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation(); e.preventDefault()
    const ll = store.map.mouseEventToLatLng(e)
    exitPick()
    centerLat.value = +ll.lat.toFixed(6)
    centerLng.value = +ll.lng.toFixed(6)
    status.value = `研究中心已设为 ${centerLat.value.toFixed(5)}, ${centerLng.value.toFixed(5)}`
    if (rangeLoaded.value) loadRange()
  }
  pickListenerRef.value = listener
  container.addEventListener('click', listener, true)
}

// ---------- 选址模拟 ----------
async function runSiteSelection() {
  if (!rangeLoaded.value) await loadRange()
  if (loading.value) return
  loading.value = true
  status.value = `选址分析 ${catLabel()} ${timeBudget.value}min…`
  const r = await api.planningSiteSelection(
    category.value, mode.value, timeBudget.value, currentBBox(), nCandidates.value, extraCands.value)
  loading.value = false
  if (!r.ok) { status.value = `选址失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  renderRange()
  renderSiteCands(r.data.candidates)
  result.value = r.data
  activeCandIdx.value = -1
  status.value = `已评估 ${r.data.n_candidates} 个候选 | 现有覆盖 ${r.data.exist_coverage_population.toLocaleString()} 人 | 推荐前 ${r.data.candidates.length} 名`
}

// 仅评估手动候选的选址效果
async function runManualEval() {
  if (!extraCands.value.length) { status.value = '请先手动添加候选点'; return }
  if (!rangeLoaded.value) await loadRange()
  if (loading.value) return
  loading.value = true
  status.value = `计算 ${extraCands.value.length} 个手动候选效果…`
  const r = await api.planningSiteSelection(
    category.value, mode.value, timeBudget.value, currentBBox(), extraCands.value.length, extraCands.value, false)
  loading.value = false
  if (!r.ok) { status.value = `计算失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  renderRange()
  renderSiteCands(r.data.candidates)
  result.value = r.data
  activeCandIdx.value = -1
  status.value = `已评估 ${r.data.n_candidates} 个手动候选 | 现有覆盖 ${r.data.exist_coverage_population.toLocaleString()} 人`
}

let candMarkers = []
function renderSiteCands(list) {
  candMarkers = []
  list.forEach((c, i) => {
    const color = i === activeCandIdx.value ? '#d32f2f' : (i < 3 ? '#f57c00' : '#90a4ae')
    const mk = L.circleMarker([c.lat, c.lng], {
      radius: i === activeCandIdx.value ? 10 : 8, color: '#fff', weight: 1.5,
      fillColor: color, fillOpacity: 0.95,
    }).bindPopup(
      `<div class="pop-pop"><div class="pp-title">${i + 1}. ${c.name || '候选点'}</div>` +
      `覆盖人口 <b>${c.coverage_population.toLocaleString()}</b><br/>` +
      `填补盲区 <b style="color:#d32f2f">${c.fill_population.toLocaleString()}</b><br/>` +
      `重叠 <b>${c.overlap_population.toLocaleString()}</b><br/>` +
      `评分 <b>${c.score}</b></div>`, { maxWidth: 280 })
    mk.on('click', () => selectCandidate(i))
    addOverlay(mk)
    candMarkers.push(mk)
  })
}

function selectCandidate(idx) {
  activeCandIdx.value = idx
  const c = result.value?.candidates?.[idx]
  if (!c) return
  // 重新渲染候选点高亮
  clearOverlays()
  renderRange()
  renderSiteCands(result.value.candidates)
  if (store.map) store.map.setView([c.lat, c.lng], Math.max(store.map.getZoom(), 14))
  status.value = `候选 ${idx + 1}. ${c.name} | 覆盖 ${c.coverage_population.toLocaleString()} | 填补盲区 ${c.fill_population.toLocaleString()}`
}

function addManualCandidate() {
  picking.value = true
  pickFor.value = 'site'
  setPickMode(true)
  status.value = '选点模式：点击地图添加选址候选点（限研究范围内）'
  const container = store.map.getContainer()
  const listener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation(); e.preventDefault()
    const ll = store.map.mouseEventToLatLng(e)
    exitPick()
    if (ll) {
      // 检查是否在研究范围内
      const b = currentBBox()
      if (ll.lng < b[0] || ll.lng > b[2] || ll.lat < b[1] || ll.lat > b[3]) {
        status.value = '候选点超出研究范围，请在地图框内选择'
        return
      }
      extraCands.value.push({ lat: +ll.lat.toFixed(6), lng: +ll.lng.toFixed(6), name: `手动候选${extraCands.value.length + 1}` })
      renderFacilityPin({ lat: ll.lat, lng: ll.lng, name: `手动候选${extraCands.value.length}`, address: '' }, '#7b1fa2')
      status.value = `已添加候选 (${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)})，共 ${extraCands.value.length} 个手动候选`
    }
  }
  pickListenerRef.value = listener
  container.addEventListener('click', listener, true)
}

// ---------- 关闭影响 ----------
function toggleCloseTarget(f) {
  const idx = closeTargets.value.findIndex((x) => x.id === f.id)
  if (idx >= 0) closeTargets.value.splice(idx, 1)
  else closeTargets.value.push({ ...f })
}

async function runClosure() {
  if (!closeTargets.value.length) { status.value = '请先勾选要评估的设施'; return }
  loading.value = true
  status.value = '计算关闭影响…'
  const r = await api.planningClosure(
    null, mode.value, timeBudget.value, closeFallback.value, null, tier.value,
    closeTargets.value.map((f) => f.id))
  loading.value = false
  if (!r.ok) { status.value = `关闭影响失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  renderRange()
  closeTargets.value.forEach((f) => renderFacilityPin(f, '#d32f2f', '评估目标'))
  if (r.data.polygon) {
    addGeoJson(r.data.polygon, { color: '#d32f2f', weight: 2, fillColor: '#d32f2f', fillOpacity: 0.25 })
  }
  r.data.replacement_facilities.forEach((f) => {
    renderFacilityPin({ lat: f.lat, lng: f.lng, name: f.name, address: `替代·${f.distance_m}m` }, '#2e7d32', '替代')
  })
  result.value = r.data
  status.value = `受影响 ${r.data.affected_population.toLocaleString()} 人 | 完全失去 ${r.data.lost_population.toLocaleString()} | 退级 ${r.data.downgraded_population.toLocaleString()} | ${r.data.replacement_facilities.length} 个替代设施`
}

// ---------- 搬迁影响 ----------
function selectRelocOld(f) {
  relocOld.value = { ...f }
  relocNew.value = null
  result.value = null
  clearOverlays()
  renderRange()
  renderFacilityPin(f, '#d32f2f', '旧设施')
  status.value = `旧设施: ${f.name}`
}

function pickRelocNew() {
  if (!relocOld.value) { status.value = '请先选择旧设施'; return }
  picking.value = true
  pickFor.value = 'reloc-new'
  setPickMode(true)
  status.value = '选点模式：点击地图选择新址（限研究范围内）'
  const container = store.map.getContainer()
  const listener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation(); e.preventDefault()
    const ll = store.map.mouseEventToLatLng(e)
    exitPick()
    const b = currentBBox()
    if (ll.lng < b[0] || ll.lng > b[2] || ll.lat < b[1] || ll.lat > b[3]) {
      status.value = '新址超出研究范围，请在地图框内选择'
      return
    }
    relocNew.value = { lat: ll.lat, lng: ll.lng }
    clearOverlays()
    renderRange()
    renderFacilityPin(relocOld.value, '#d32f2f', '旧设施')
    renderFacilityPin({ lat: ll.lat, lng: ll.lng, name: '新址', address: '' }, '#1976d2', '新址')
    status.value = `新址已设 (${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)})，点「计算搬迁影响」`
  }
  pickListenerRef.value = listener
  container.addEventListener('click', listener, true)
}

async function runRelocation() {
  if (!relocOld.value || !relocNew.value) { status.value = '请先选择旧设施与新址'; return }
  loading.value = true
  status.value = '计算搬迁影响…'
  const r = await api.planningRelocation(null, relocNew.value.lat, relocNew.value.lng, mode.value, timeBudget.value, relocOld.value.id, tier.value)
  loading.value = false
  if (!r.ok) { status.value = `搬迁影响失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  renderRange()
  renderFacilityPin(relocOld.value, '#d32f2f', '旧设施')
  renderFacilityPin({ lat: relocNew.value.lat, lng: relocNew.value.lng, name: '新址', address: '' }, '#1976d2', '新址')
  if (r.data.affected_polygon) addGeoJson(r.data.affected_polygon, { color: '#d32f2f', weight: 2, fillColor: '#d32f2f', fillOpacity: 0.25 })
  if (r.data.recovered_polygon) addGeoJson(r.data.recovered_polygon, { color: '#2e7d32', weight: 2, fillColor: '#2e7d32', fillOpacity: 0.35 })
  if (r.data.added_polygon) addGeoJson(r.data.added_polygon, { color: '#1976d2', weight: 2, fillColor: '#1976d2', fillOpacity: 0.25 })
  result.value = r.data
  status.value = `受影响 ${r.data.affected_population.toLocaleString()} | 恢复 ${r.data.recovered_population.toLocaleString()} | 新增覆盖 ${r.data.added_population.toLocaleString()} | 净变化 ${r.data.net_change > 0 ? '+' : ''}${r.data.net_change.toLocaleString()}`
}

function renderFacilityPin(p, color = '#e65100', label = '') {
  const mk = L.circleMarker([p.lat, p.lng], {
    radius: 6, color: '#fff', weight: 1.5, fillColor: color, fillOpacity: 0.95,
  }).bindPopup(
    `<div class="pop-pop"><div class="pp-title">${p.name || label}</div>` +
    `${p.address ? `地址 <b>${p.address}</b><br/>` : ''}` +
    `(${p.lng.toFixed(5)}, ${p.lat.toFixed(5)})</div>`, { maxWidth: 280 })
  addOverlay(mk)
  return mk
}

function onClear() {
  clearOverlays()
  result.value = null
  closeTargets.value = []
  relocOld.value = null
  relocNew.value = null
  extraCands.value = []
  rangeLoaded.value = false
  rangeFacilities.value = []
  rangeMeta.value = null
  activeCandIdx.value = -1
  status.value = '就绪'
}

// 参数变化时若已加载范围则重新加载
watch([category, mode, timeBudget, radiusKm, tier], () => {
  if (rangeLoaded.value) loadRange()
})

let pickListenerRef = ref(null)
function exitPick() {
  picking.value = false
  setPickMode(false)
  if (pickListenerRef.value) {
    store.map.getContainer().removeEventListener('click', pickListenerRef.value, true)
    pickListenerRef.value = null
  }
}
onBeforeUnmount(exitPick)

function fmtN(v) { return (v || 0).toLocaleString() }
</script>

<template>
  <div class="planning-view">
    <aside class="panel">
      <div class="title">规划分析</div>

      <div class="sub-tabs">
        <button :class="['sub-tab', { active: subtab === 'site' }]" @click="subtab = 'site'">选址模拟</button>
        <button :class="['sub-tab', { active: subtab === 'closure' }]" @click="subtab = 'closure'">关闭影响</button>
        <button :class="['sub-tab', { active: subtab === 'relocation' }]" @click="subtab = 'relocation'">搬迁影响</button>
      </div>

      <!-- 公共参数 -->
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
      <div class="row">
        <span class="lbl">模式</span>
        <select v-model="mode" class="grow">
          <option v-for="m in MODES" :key="m.v" :value="m.v">{{ m.l }}</option>
        </select>
      </div>
      <div class="row">
        <span class="lbl">阈值</span>
        <div class="presets">
          <button v-for="t in TIME_PRESETS" :key="t"
                  :class="['preset', { active: timeBudget === t }]" @click="timeBudget = t">{{ t }}min</button>
        </div>
      </div>
      <div class="row">
        <span class="lbl">范围</span>
        <input type="range" min="1" max="10" step="0.5" v-model.number="radiusKm" class="grow" />
        <span class="val">{{ radiusKm }} km</span>
      </div>
      <div class="row">
        <span class="lbl">中心</span>
        <input type="text" class="grow" readonly
               :value="centerLat.toFixed(5) + ', ' + centerLng.toFixed(5)" />
        <button class="btn" @click="pickCenter">选点</button>
      </div>
      <div class="row">
        <button class="btn primary grow" @click="loadRange">加载研究范围</button>
      </div>

      <!-- 研究范围状态 -->
      <div class="range-info" v-if="rangeLoaded">
        <div class="ri-line"><span>范围内设施</span><b>{{ rangeFacilities.length }} 个</b></div>
        <div class="ri-line"><span>范围覆盖率</span><b>{{ (rangeMeta.coverage_rate * 100).toFixed(1) }}%</b></div>
        <div class="ri-line"><span>盲区人口</span><b class="warn">{{ fmtN(rangeMeta.blind_population) }}</b></div>
      </div>

      <!-- 选址模拟 -->
      <template v-if="subtab === 'site'">
        <div class="row">
          <span class="lbl">推荐数</span>
          <input type="number" min="1" max="20" v-model.number="nCandidates" class="grow" />
        </div>
        <div class="row" v-if="extraCands.length">
          <span class="lbl">手动</span>
          <span class="grow hint-inline">{{ extraCands.length }} 个手动候选</span>
          <button class="btn" @click="extraCands = []">清空</button>
        </div>
        <div class="row">
          <button class="btn primary grow" @click="runSiteSelection">生成选址推荐</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div class="row">
          <button class="btn grow" :class="{ active: picking && pickFor === 'site' }" @click="picking ? exitPick() : addManualCandidate()">手动加候选点</button>
          <button class="btn" :disabled="!extraCands.length" @click="runManualEval">计算效果</button>
        </div>
        <div class="hint">盲区参考已加载（红=盲区/黄=紧张/绿=覆盖）。自动生成范围内候选，可手动补点。评分 = 填补盲区×1 + 覆盖×0.5 − 重叠×0.6。点击候选卡片可在地图定位。</div>

        <div class="result-list" v-if="result && result.candidates">
          <div v-for="(c, i) in result.candidates" :key="i"
               class="r-item" :class="{ top: i === 0, active: i === activeCandIdx }"
               @click="selectCandidate(i)">
            <span class="r-rank">{{ i + 1 }}</span>
            <div class="r-main">
              <div class="r-name">{{ c.name }} <em>{{ c.source === 'manual' ? '·手动' : '' }}</em></div>
              <div class="r-meta">覆盖 {{ fmtN(c.coverage_population) }} · 填补 {{ fmtN(c.fill_population) }} · 重叠 {{ fmtN(c.overlap_population) }}</div>
            </div>
            <span class="r-score">{{ c.score }}</span>
          </div>
        </div>
      </template>

      <!-- 关闭影响 -->
      <template v-if="subtab === 'closure'">
        <div class="row">
          <span class="lbl">退级</span>
          <input type="number" min="15" max="60" v-model.number="closeFallback" class="grow" />
          <span class="val">{{ closeFallback }}min</span>
        </div>
        <div class="hint" v-if="!rangeLoaded">请先「加载研究范围」查看范围内设施</div>
        <div class="fac-list" v-if="rangeLoaded">
          <div v-for="(f, i) in rangeFacilities" :key="f.id"
               class="fac-item" :class="{ picked: closeTargets.some((x) => x.id === f.id) }"
               @click="toggleCloseTarget(f)">
            <input type="checkbox" :checked="closeTargets.some((x) => x.id === f.id)" @click.stop="toggleCloseTarget(f)" />
            <div class="fac-main">
              <div class="fac-name">{{ f.name || '(未命名)' }}</div>
              <div class="fac-meta">{{ f.address || `(${f.lng.toFixed(4)}, ${f.lat.toFixed(4)})` }}</div>
            </div>
            <span class="fac-idx">{{ i + 1 }}</span>
          </div>
        </div>
        <div class="row" v-if="rangeLoaded">
          <button class="btn primary grow" @click="runClosure">计算关闭影响 ({{ closeTargets.length }})</button>
          <button class="btn" @click="closeTargets = []">清空</button>
        </div>
        <div class="stats" v-if="result && result.affected_population !== undefined">
          <div class="stat"><span>受影响人口</span><b class="warn">{{ fmtN(result.affected_population) }}</b></div>
          <div class="stat"><span>完全失去</span><b>{{ fmtN(result.lost_population) }}</b></div>
          <div class="stat"><span>退级</span><b>{{ fmtN(result.downgraded_population) }}</b></div>
          <div class="stat"><span>替代设施</span><b>{{ result.replacement_facilities.length }}</b></div>
        </div>
        <div class="hint">在列表中勾选或<b>点击地图上的橙色设施点</b>选择要评估的设施。红区=受影响（独占覆盖），绿点=替代设施。</div>
      </template>

      <!-- 搬迁影响 -->
      <template v-if="subtab === 'relocation'">
        <div class="hint" v-if="!rangeLoaded">请先「加载研究范围」选择旧设施</div>
        <div class="fac-list" v-if="rangeLoaded">
          <div v-for="(f, i) in rangeFacilities" :key="f.id"
               class="fac-item" :class="{ picked: relocOld && relocOld.id === f.id }"
               @click="selectRelocOld(f)">
            <span class="fac-dot" :class="{ on: relocOld && relocOld.id === f.id }"></span>
            <div class="fac-main">
              <div class="fac-name">{{ f.name || '(未命名)' }}</div>
              <div class="fac-meta">{{ f.address || `(${f.lng.toFixed(4)}, ${f.lat.toFixed(4)})` }}</div>
            </div>
            <span class="fac-idx">{{ i + 1 }}</span>
          </div>
        </div>
        <div class="row" v-if="relocOld">
          <span class="lbl">旧</span>
          <span class="grow hint-inline">{{ relocOld.name }}</span>
        </div>
        <div class="row">
          <button class="btn grow" :class="{ active: picking && pickFor === 'reloc-new' }" @click="picking ? exitPick() : pickRelocNew()">选新址</button>
        </div>
        <div class="row">
          <button class="btn primary grow" @click="runRelocation">计算搬迁影响</button>
          <button class="btn" @click="onClear">清空</button>
        </div>
        <div class="stats" v-if="result && result.net_change !== undefined">
          <div class="stat"><span>受影响</span><b class="warn">{{ fmtN(result.affected_population) }}</b></div>
          <div class="stat"><span>恢复</span><b>{{ fmtN(result.recovered_population) }}</b></div>
          <div class="stat"><span>新增覆盖</span><b>{{ fmtN(result.added_population) }}</b></div>
          <div class="stat"><span>净变化</span><b :style="{ color: result.net_change >= 0 ? '#2e7d32' : '#d32f2f' }">{{ result.net_change > 0 ? '+' : '' }}{{ fmtN(result.net_change) }}</b></div>
        </div>
        <div class="hint">点击<b>地图上的橙色设施点</b>或列表选择旧设施，再选新址。红=受影响区，绿=恢复区，蓝=新增覆盖。净变化 = 恢复 + 新增 − 受影响。</div>
      </template>
    </aside>
    <div id="status">{{ status }}</div>
  </div>
</template>

<style scoped>
.planning-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; left: 12px; z-index: 1000; width: 320px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px;
  pointer-events: auto; max-height: calc(100vh - 80px); overflow-y: auto;
}
.title { font-weight: 600; font-size: 14px; margin-bottom: 8px; }
.sub-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
.sub-tab {
  flex: 1; border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 7px; padding: 5px 0; font-size: 12.5px; cursor: pointer;
}
.sub-tab.active { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.row { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; }
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
.btn { border: 1px solid var(--border); background: #fff; color: var(--text); padding: 5px 10px; border-radius: 8px; font-size: 12.5px; cursor: pointer; }
.btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); color: #fff; }
.btn.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.hint { color: var(--text-3); font-size: 11.5px; line-height: 1.6; }
.hint-inline { color: var(--text-2); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.range-info { border: 1px solid var(--primary-light); background: var(--primary-light); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.ri-line { display: flex; justify-content: space-between; font-size: 12px; padding: 1px 0; }
.ri-line span { color: var(--text-2); }
.ri-line b { color: var(--primary-dark); }
.ri-line b.warn { color: #d32f2f; }
.fac-list { max-height: 260px; overflow-y: auto; margin-bottom: 8px; }
.fac-item { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 4px; cursor: pointer; }
.fac-item:hover { border-color: var(--primary); background: var(--primary-light); }
.fac-item.picked { border-color: var(--primary); background: var(--primary-light); }
.fac-item input { accent-color: var(--primary); }
.fac-main { flex: 1; min-width: 0; }
.fac-name { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fac-meta { font-size: 11px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fac-idx { width: 18px; height: 18px; border-radius: 50%; background: #eceff1; color: var(--text-2); font-size: 11px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.fac-dot { width: 10px; height: 10px; border-radius: 50%; border: 2px solid #b0bec5; flex-shrink: 0; }
.fac-dot.on { background: #d32f2f; border-color: #d32f2f; }
.stats { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.stat {
  flex: 1 1 40%; border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px;
  display: flex; flex-direction: column; gap: 2px; text-align: center;
}
.stat span { font-size: 11px; color: var(--text-3); }
.stat b { font-size: 13px; color: var(--primary-dark); }
.stat b.warn { color: #d32f2f; }
.result-list { margin-top: 8px; }
.r-item { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 5px; cursor: pointer; }
.r-item:hover { border-color: var(--primary); }
.r-item.top { border-color: var(--primary); background: var(--primary-light); }
.r-item.active { border-color: #d32f2f; box-shadow: 0 0 0 2px rgba(211,47,47,.2); }
.r-rank { width: 20px; height: 20px; border-radius: 50%; background: #cfd8dc; color: #37474f; font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.r-item.top .r-rank { background: var(--primary); color: #fff; }
.r-main { flex: 1; min-width: 0; }
.r-name { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.r-name em { color: var(--text-3); font-style: normal; font-size: 11px; }
.r-meta { font-size: 11px; color: var(--text-2); }
.r-score { font-size: 15px; font-weight: 700; color: var(--primary); flex-shrink: 0; }
#status {
  position: fixed; left: 12px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 60%;
}
</style>

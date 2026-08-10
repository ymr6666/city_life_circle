<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { store } from '../store'
import {
  drawIsochrone, drawReverse, clearRoads, scheduleRoads, clearOverlays,
  setCurrentPoint, setPickMode, addLabeledMarker, clearCurrentPoint,
} from '../mapLayers'
import StatsPanel from '../components/StatsPanel.vue'
import ScoreCard from '../components/ScoreCard.vue'
import ChartBox from '../components/ChartBox.vue'
import { decayLineOption } from '../chartOptions'

// ---------- 常量 ----------
const MODES = [
  { v: 'walk', l: '步行', color: '#1976d2' },
  { v: 'cycle', l: '骑行', color: '#2e7d32' },
  { v: 'drive', l: '驾车', color: '#f57c00' },
  { v: 'walk+metro', l: '地铁', color: '#8e24aa' },
  { v: 'walk+bus', l: '公交', color: '#00838f' },
  { v: 'walk+metro+bus', l: '公交+地铁', color: '#e53935' },
]
const MODE_COLOR = Object.fromEntries(MODES.map((m) => [m.v, m.color]))
const MODE_LABEL = Object.fromEntries(MODES.map((m) => [m.v, m.l]))
const PALETTE = ['#1976d2', '#e53935', '#2e7d32', '#f57c00', '#8e24aa', '#00838f', '#6d4c41', '#5e35b1']
const DIM_LABEL = { medical: '医疗', education: '教育', shopping: '购物', leisure: '休闲', transit: '交通' }
function labelOf(k) { return DIM_LABEL[k] || k }

// ---------- 状态 ----------
const lat = ref(31.861)
const lng = ref(117.285)
const addr = ref('')
const searchText = ref('')
const selectedModes = ref(['walk'])
const lastMode = ref('walk')   // 最近一次勾选的出行方式 (反算/路网按此方式)
const time = ref(15)
const status = ref('')
const rightTab = ref('stats')
const showRoads = ref(false)
const showPoints = ref(true)
const showFacilities = ref(true)
const weights = ref({ medical: 1, education: 1, shopping: 1, leisure: 1, transit: 1 })
const family = ref('none')
const lastReverse = ref(null)
const pickMode = ref(false)
const scoreLoading = ref(false)
// 覆盖率-时间曲线
const curveLoading = ref(false)
const curve = ref(null)   // {points: [...]} 当前点当前模式
const curveMode = ref(null)  // 曲线界面对应出行方式 (单选)

// 分析点: {id, lat, lng, address, color, visible,
//          results: {mode: {iso, stats, score}}, viewedMode}
let nextPointId = 1
const points = ref([])
const activePointId = ref(null)
let locationCleared = false   // 清空后切 Tab 不再重建"当前位置"残留点

const activePoint = computed(() => points.value.find((p) => p.id === activePointId.value) || null)
// 当前查看的模式 (用户选择或第一个有结果的方式)
const viewedMode = computed(() => {
  const pt = activePoint.value
  if (!pt || !pt.results) return null
  if (pt.viewedMode && pt.results[pt.viewedMode]) return pt.viewedMode
  return Object.keys(pt.results).find((k) => pt.results[k]) || null
})
// 统计展示用模式: 优先查看模式, 否则回退到有 iso 的结果
const statsMode = computed(() => {
  const pt = activePoint.value
  const m = viewedMode.value
  if (pt && m && pt.results[m] && pt.results[m].stats) return m
  if (!pt || !pt.results) return null
  return Object.keys(pt.results).find((k) => pt.results[k] && pt.results[k].stats) || null
})
const stats = computed(() => {
  const pt = activePoint.value
  const m = statsMode.value
  return (pt && m && pt.results[m]) ? pt.results[m].stats : null
})
const score = computed(() => {
  const pt = activePoint.value
  const m = viewedMode.value
  if (pt && m && pt.results[m] && pt.results[m].score) return pt.results[m].score
  if (!pt || !pt.results) return null
  const mk = Object.keys(pt.results).find((k) => pt.results[k] && pt.results[k].score)
  return mk ? pt.results[mk].score : null
})
const resultModes = computed(() => {
  const pt = activePoint.value
  if (!pt || !pt.results) return []
  return Object.keys(pt.results)
    .filter((m) => pt.results[m])
    .map((m) => ({ m, color: MODE_COLOR[m], label: MODE_LABEL[m] }))
})

// ---------- 工具 ----------
function statusText(msg) { status.value = msg }
function fmtPop(p) {
  if (p == null) return '—'
  return p >= 10000 ? (p / 10000).toFixed(1) + '万' : String(p)
}
function findPoint(la, ln) {
  return points.value.find((p) => Math.abs(p.lat - la) < 1e-5 && Math.abs(p.lng - ln) < 1e-5)
}
function makePoint(la, ln) {
  const pt = {
    id: nextPointId++,
    lat: la, lng: ln, address: addr.value || '',
    color: PALETTE[(points.value.length) % PALETTE.length],
    visible: true, results: {}, viewedMode: null, modeVisible: {},
  }
  points.value.push(pt)
  // 必须返回 reactive 代理, 否则后续 pt.results 的写入绕过响应式导致 computed 不失效
  return points.value[points.value.length - 1]
}
function ptName(pt) {
  const i = points.value.indexOf(pt)
  return i >= 0 ? `P${i + 1}` : ''
}
function buildStats(iso) {
  return {
    facilities_by_category: iso.facilities_by_category,
    pois_by_category: iso.pois_by_category,
    reachable_pois_count: iso.reachable_pois_count,
    reachable_facilities_count: iso.reachable_facilities_count,
    metro_stations: iso.reachable_metro_stations_count,
    bus_stops: iso.reachable_bus_stops_count,
    population: iso.reachable_population,
    population_density: iso.population_density_per_km2,
  }
}
function setActivePoint(pt) {
  activePointId.value = pt.id
  locationCleared = false
  lat.value = pt.lat
  lng.value = pt.lng
  addr.value = pt.address
  store.pointLat = pt.lat
  store.pointLng = pt.lng
  setCurrentPoint(pt.lat, pt.lng, pt.address)
  if (store.map) store.map.setView([pt.lat, pt.lng], Math.max(store.map.getZoom(), 14))
  statusText(`当前分析点 ${ptName(pt)}：${pt.address || `${pt.lat.toFixed(5)}, ${pt.lng.toFixed(5)}`}`)
}
function togglePointVisible(pt) { pt.visible = !pt.visible; redrawLayers() }
function removePoint(pt) {
  const idx = points.value.indexOf(pt)
  if (idx >= 0) points.value.splice(idx, 1)
  lastReverse.value = null   // 设施来自分析点, 移除后旧范围失效
  if (activePointId.value === pt.id) {
    activePointId.value = points.value[Math.max(0, idx - 1)]?.id || null
    if (activePoint.value) setCurrentPoint(activePoint.value.lat, activePoint.value.lng, activePoint.value.address)
    else { clearCurrentPoint(); locationCleared = true }
  }
  redrawLayers()
}
function clearPoints() {
  points.value = []
  activePointId.value = null
  locationCleared = true
  lastReverse.value = null
  clearOverlays()
  clearCurrentPoint()
  statusText('已清空分析点')
}
function addPointFromCurrent() {
  const la = parseFloat(lat.value), ln = parseFloat(lng.value)
  if (isNaN(la) || isNaN(ln)) { statusText('当前坐标非法'); return }
  let pt = findPoint(la, ln)
  if (!pt) pt = makePoint(la, ln)
  setActivePoint(pt)
  redrawLayers()
  statusText(`已添加分析点 ${ptName(pt)}`)
}

// ---------- 当前位置 ----------
async function applyPoint(la, ln, keepActive = false) {
  lat.value = la
  lng.value = ln
  locationCleared = false
  addr.value = ''
  store.pointLat = la
  store.pointLng = ln
  setCurrentPoint(la, ln, '')
  const r = await api.regeo(la, ln)
  if (r.ok && r.data && r.data.address) {
    addr.value = r.data.address
    setCurrentPoint(la, ln, r.data.address)
  }
  const pt = findPoint(la, ln)
  activePointId.value = pt ? pt.id : (keepActive ? activePointId.value : null)
  redrawLayers()
  statusText(`已定位：${addr.value || `${la.toFixed(6)}, ${ln.toFixed(6)}`}`)
}

// ---------- 地图选点 (分析点) ----------
let pickListener = null
function enterPick() {
  pickMode.value = true
  setPickMode(true)
  statusText('选点模式：在地图上点击选取位置')
  const container = store.map.getContainer()
  pickListener = (e) => {
    if (e.target.closest('.leaflet-control')) return
    e.stopPropagation()
    e.preventDefault()
    const ll = store.map.mouseEventToLatLng(e)
    exitPick()
    if (ll) {
      applyPoint(+ll.lat.toFixed(6), +ll.lng.toFixed(6))
    }
  }
  container.addEventListener('click', pickListener, true)
}
function exitPick() {
  pickMode.value = false
  setPickMode(false)
  if (pickListener) {
    store.map.getContainer().removeEventListener('click', pickListener, true)
    pickListener = null
  }
}
function togglePick() {
  if (pickMode.value) { exitPick(); statusText('已退出选点模式') }
  else { enterPick() }
}

async function doGeocode() {
  const kw = searchText.value.trim()
  if (!kw) { statusText('请输入地址关键词'); return }
  statusText('搜索地址…')
  const r = await api.geocode(kw)
  if (!r.ok || !r.data.results || !r.data.results.length) { statusText('未找到该地址'); return }
  const hit = r.data.results[0]
  await applyPoint(hit.lat, hit.lng)
  if (store.map) store.map.setView([hit.lat, hit.lng], 15)
}

// ---------- 出行方式多选 ----------
function toggleMode(v) {
  const i = selectedModes.value.indexOf(v)
  if (i >= 0) {
    if (selectedModes.value.length > 1) {
      selectedModes.value.splice(i, 1)
      if (lastMode.value === v) lastMode.value = selectedModes.value[selectedModes.value.length - 1]
    }
  } else {
    selectedModes.value.push(v)
    lastMode.value = v
  }
}

// ---------- 图层重绘 (多模式范围线) ----------
function redrawLayers() {
  clearOverlays()
  points.value.forEach((pt) => {
    if (!pt.visible) return
    try {
      // 仅渲染: 有 iso + 左栏已勾选该方式 + 未在右栏关闭
      const modes = Object.keys(pt.results || {})
        .filter((m) => pt.results[m] && pt.results[m].iso
          && selectedModes.value.includes(m) && pt.modeVisible[m] !== false)
      modes.forEach((m) => {
        const isViewed = pt.id === activePointId.value && m === statsMode.value
        drawIsochrone(pt.results[m].iso, {
          color: MODE_COLOR[m],
          showPoints: showPoints.value && isViewed,
          showFacilities: showFacilities.value && isViewed,
          outlineOnly: !isViewed,
        })
      })
      if (pt.id !== activePointId.value) {
        addLabeledMarker(pt.lat, pt.lng, ptName(pt), pt.color)
      }
    } catch (e) {
      console.error('[redrawLayers] 分析点绘制失败', ptName(pt), e)
    }
  })
  if (lastReverse.value) {
    try {
      drawReverse(lastReverse.value, {
        facilities: points.value.map((p) => ({ lat: p.lat, lng: p.lng, name: p.address || '', address: p.address || '' })),
        pointColors: points.value.map((p) => p.color),
        modeColor: MODE_COLOR[lastReverse.value.mode || 'walk'] || '#1976d2',
      })
    } catch (e) {
      console.error('[redrawLayers] 反算范围绘制失败', e)
    }
  }
}
watch([showPoints, showFacilities], redrawLayers)
watch(viewedMode, () => { if (rightTab.value === 'stats' || rightTab.value === 'score') redrawLayers() })
// 切回分析页时重建中心点标记 (v-show 下 onMounted 不重跑)
watch(() => store.activeTab, (v) => {
  if (v === 'analysis') {
    if (locationCleared) return
    const pt = activePoint.value
    if (pt) setCurrentPoint(pt.lat, pt.lng, pt.address)
    else setCurrentPoint(lat.value, lng.value, addr.value)
  }
})

// ---------- 正算 (多模式) ----------
async function doIso() {
  const la = parseFloat(lat.value), ln = parseFloat(lng.value)
  if (isNaN(la) || isNaN(ln)) { statusText('请输入合法坐标'); return }
  if (!selectedModes.value.length) { statusText('请至少选择一种出行方式'); return }
  let pt = findPoint(la, ln)
  if (!pt) pt = makePoint(la, ln)
  activePointId.value = pt.id
  const t0 = Date.now()
  store.loading = true
  for (const m of selectedModes.value) {
    store.loadingMsg = `计算 ${MODE_LABEL[m]} 等时圈…`
    const r = await api.isochrone(la, ln, m, time.value)
    if (r.ok) {
      pt.results[m] = { iso: r.data, stats: buildStats(r.data), score: null }
    } else {
      pt.results[m] = null
    }
  }
  store.loading = false
  if (!pt.viewedMode || !pt.results[pt.viewedMode]) {
    pt.viewedMode = Object.keys(pt.results).find((k) => pt.results[k]) || null
  }
  redrawLayers()
  rightTab.value = 'stats'
  const ok = Object.keys(pt.results).filter((k) => pt.results[k])
  const desc = ok.map((m) => `${MODE_LABEL[m]} ${pt.results[m].iso.reachable_facilities_count}设施`).join(' / ')
  statusText(`${ptName(pt)} ${ok.length} 种方式：${desc} (${((Date.now() - t0) / 1000).toFixed(1)}s)`)
}

function setViewedMode(m) {
  const pt = activePoint.value
  if (!pt) return
  pt.viewedMode = m
  if (rightTab.value === 'score') runScore(true)
  redrawLayers()
}

// 覆盖率-时间曲线: 对当前点指定方式, 一次多阈值计算
async function loadCurve() {
  const pt = activePoint.value
  const available = Object.keys(pt?.results || {}).filter((k) => pt.results[k])
  if (curveMode.value && !available.includes(curveMode.value)) curveMode.value = null
  const m = curveMode.value || viewedMode.value
  if (!pt || !m) return
  curveLoading.value = true
  const r = await api.coverageCurve(pt.lat, pt.lng, m)
  curveLoading.value = false
  if (r.ok && r.data && r.data.points) curve.value = r.data
  else curve.value = null
}

// 曲线界面单选出行方式
function setCurveMode(m) {
  curveMode.value = m
  curve.value = null
  loadCurve()
}
// 切换分析点时重置曲线方式与数据
watch(activePointId, () => { curveMode.value = null; curve.value = null })

// 曲线图配置 (人口覆盖 + 设施覆盖 双轴)
const curveOption = computed(() => {
  if (!curve.value) return null
  const pts = curve.value.points
  const x = pts.map((p) => p.time_budget_min)
  return decayLineOption({
    x,
    series: [
      { name: '覆盖人口', data: pts.map((p) => p.covered_population), color: '#1976d2', area: true, yAxisIndex: 0 },
      { name: '覆盖设施', data: pts.map((p) => p.reachable_facilities_count), color: '#f57c00', yAxisIndex: 1 },
    ],
  })
})

// 切换某交通方式缓冲区的显隐
function toggleModeVisible(m) {
  const pt = activePoint.value
  if (!pt) return
  pt.modeVisible[m] = !(pt.modeVisible[m] !== false)
  // 若关闭的是当前查看的模式, 自动切到另一个可见模式
  if (pt.modeVisible[m] === false && pt.viewedMode === m) {
    const next = Object.keys(pt.results).find(
      (k) => pt.results[k] && pt.results[k].iso && pt.modeVisible[k] !== false)
    pt.viewedMode = next || null
  }
  redrawLayers()
}
function isModeVisible(m) {
  const pt = activePoint.value
  return pt ? (pt.modeVisible[m] !== false) : true
}

// ---------- 评分 ----------
let scoreTimer = null
function runScore(silent = false) {
  const la = parseFloat(lat.value), ln = parseFloat(lng.value)
  if (isNaN(la) || isNaN(ln)) { statusText('请输入合法坐标'); return }
  const m = viewedMode.value || selectedModes.value[0] || 'walk'
  if (!silent) { store.loading = true; store.loadingMsg = '计算宜居评分' }
  scoreLoading.value = true
  api.score(la, ln, m, time.value, weights.value, family.value)
    .then((r) => {
      store.loading = false
      scoreLoading.value = false
      if (!r.ok) { if (!silent) statusText(`评分失败: ${r.data.error || r.status}`); return }
      let pt = findPoint(la, ln)
      if (!pt) pt = makePoint(la, ln)
      if (!pt.results[m]) pt.results[m] = {}
      pt.results[m].score = r.data
      activePointId.value = pt.id
      if (!silent) statusText(`${ptName(pt)} ${MODE_LABEL[m]} 宜居等级 ${r.data.grade} · ${r.data.score} 分`)
    })
    .catch(() => { store.loading = false; scoreLoading.value = false })
}
watch([weights, family], () => {
  clearTimeout(scoreTimer)
  if (score.value) scoreTimer = setTimeout(() => runScore(true), 600)
}, { deep: true })

// ---------- 反算选址 ----------
// 反算设施 = 当前分析点 (统一用"＋ 设为分析点"选点, 点立即可见)
async function doReverse() {
  const list = points.value.length
    ? points.value.map((p) => ({ lat: p.lat, lng: p.lng, name: p.address || '', address: p.address || '' }))
    : [{ lat: parseFloat(lat.value), lng: parseFloat(lng.value), name: addr.value || '', address: addr.value || '' }]
  if (list.some((f) => isNaN(f.lat) || isNaN(f.lng))) { statusText('设施坐标非法'); return }
  clearOverlays()
  const rmode = modeForReverse()
  statusText(`反算 ${list.length} 个设施覆盖范围（${MODE_LABEL[rmode]}）…`)
  store.loading = true; store.loadingMsg = '反算覆盖范围'
  const r = await api.reverse(list, rmode, time.value)
  store.loading = false
  if (!r.ok) { statusText(`反算失败: ${r.data.error || r.status}`); return }
  lastReverse.value = r.data
  redrawLayers()
  const inter = r.data.intersection
  const totalOrigins = (r.data.facilities || []).reduce((s, f) => s + (f.reachable_origins_count || 0), 0)
  statusText(`覆盖起点 ${totalOrigins}` +
    (inter ? ` | 最优选址 ${inter.reachable_origins_count} 起点 / 覆盖 ${fmtPop(inter.reachable_population)}人` : ''))
}
function modeForReverse() {
  // 反算/路网用最近一次勾选的出行方式, 与"出行方式"选择一致 (不再总是回退步行)
  if (selectedModes.value.includes(lastMode.value)) return lastMode.value
  return selectedModes.value[0] || 'walk'
}
const reverseModeLabel = computed(() => MODE_LABEL[modeForReverse()] || '')

// ---------- 对比表 ----------
const comparePoints = computed(() => points.value.filter((p) => Object.values(p.results || {}).some((r) => r)))
function pointIso(pt) {
  if (!pt || !pt.results) return null
  if (pt.viewedMode && pt.results[pt.viewedMode] && pt.results[pt.viewedMode].iso) return pt.results[pt.viewedMode].iso
  const m = Object.keys(pt.results).find((k) => pt.results[k] && pt.results[k].iso)
  return m ? pt.results[m].iso : null
}
const compareRows = computed(() => {
  if (comparePoints.value.length < 2) return []
  const iso = (p) => pointIso(p)
  return [
    { label: '设施数', values: comparePoints.value.map((p) => iso(p)?.reachable_facilities_count ?? '—') },
    { label: 'POI数', values: comparePoints.value.map((p) => iso(p)?.reachable_pois_count ?? '—') },
    { label: '覆盖人口', values: comparePoints.value.map((p) => fmtPop(iso(p)?.reachable_population)) },
    { label: '密度(人/km²)', values: comparePoints.value.map((p) => (iso(p)?.population_density_per_km2 != null ? Math.round(iso(p).population_density_per_km2).toLocaleString() : '—')) },
  ]
})

// ---------- 路网 ----------
function toggleRoads() {
  clearRoads()
  if (showRoads.value && store.map) scheduleRoads(modeForReverse())
}
watch(selectedModes, () => {
  clearRoads()
  if (showRoads.value) scheduleRoads(modeForReverse())
  redrawLayers()
}, { deep: true })

// ---------- 清空 ----------
function clearAll() {
  points.value.forEach((p) => { p.results = {}; p.viewedMode = null })
  lastReverse.value = null
  clearOverlays()
  clearCurrentPoint()
  rightTab.value = 'stats'
  statusText('已清空图层与结果')
}

onMounted(async () => {
  setCurrentPoint(lat.value, lng.value, '')
  statusText(`就绪 · ${selectedModes.value.map((m) => MODE_LABEL[m]).join('+')} ${time.value} 分钟 · 点击地图或搜索定位，然后「生成生活圈」`)
  if (store.map) {
    store.map.on('moveend', () => { if (showRoads.value) scheduleRoads(modeForReverse()) })
  }
  try {
    const demo = new URLSearchParams(window.location.search).get('demo')
    if (demo) {
      const [m, t] = demo.split(':')
      if (m && MODES.some((x) => x.v === m)) selectedModes.value = [m]
      if (t && !isNaN(parseInt(t, 10))) time.value = parseInt(t, 10)
      await doIso()
    }
  } catch (e) { /* 演示参数解析失败忽略 */ }
})
onBeforeUnmount(() => {
  if (store.map && pickListener) store.map.getContainer().removeEventListener('click', pickListener, true)
})
</script>

<template>
  <div class="analysis-view">
    <!-- 左侧控制面板: 定位 + 出行 -->
    <aside class="panel left">
      <section class="sec">
        <div class="sec-title">定位</div>
        <div class="row">
          <input type="text" class="grow" v-model="searchText" placeholder="搜索地址，如 合肥南站"
                 @keydown.enter="doGeocode" />
          <button class="btn" @click="doGeocode">搜索</button>
        </div>
        <div class="addr-box">
          <div class="addr-text">{{ addr || '点击地图或搜索定位，将显示地址' }}</div>
          <div class="addr-coord">{{ lat.toFixed(6) }}, {{ lng.toFixed(6) }}</div>
        </div>
        <div class="row">
          <button class="btn grow" :class="{ active: pickMode }" @click="togglePick">
            {{ pickMode ? '选点中… 点击地图' : '在地图上点选位置' }}
          </button>
          <button class="btn" @click="addPointFromCurrent" title="把当前位置加入分析点列表">+ 设为分析点</button>
        </div>

        <div class="pt-list" v-if="points.length">
          <div class="pt-head">
            <span>分析点 ({{ points.length }})</span>
            <button class="link-btn" @click="clearPoints">清空</button>
          </div>
          <div class="pt-items">
          <div v-for="(pt, i) in points" :key="pt.id"
               :class="['pt-item', { active: pt.id === activePointId, dim: !pt.visible }]">
            <span class="pt-color" :style="{ background: pt.color }"
                  @click="togglePointVisible(pt)" :title="pt.visible ? '隐藏该点图层' : '显示该点图层'"></span>
            <span class="pt-main" @click="setActivePoint(pt)">
              <span class="pt-name">P{{ i + 1 }}<template v-if="pt.viewedMode && pt.results[pt.viewedMode] && pt.results[pt.viewedMode].iso"> · {{ fmtPop(pt.results[pt.viewedMode].iso.reachable_population) }}人</template></span>
              <span class="pt-addr">{{ pt.address || `${pt.lat.toFixed(5)}, ${pt.lng.toFixed(5)}` }}</span>
            </span>
            <span class="pt-actions">
              <button class="link-btn" @click.stop="rightTab = 'stats'; setActivePoint(pt)">结果</button>
              <button class="link-btn" @click.stop="removePoint(pt)">×</button>
            </span>
          </div>
          </div>
        </div>
        <div class="hint" v-if="!points.length">添加多个分析点，可分别生成生活圈并同图对比</div>
      </section>

      <section class="sec">
        <div class="sec-title">出行 · 可多选</div>
        <div class="mode-grid">
          <button v-for="m in MODES" :key="m.v"
                  :class="['mode-btn', { active: selectedModes.includes(m.v) }]"
                  :style="selectedModes.includes(m.v) ? { background: m.color, borderColor: m.color } : {}"
                  @click="toggleMode(m.v)">{{ m.l }}</button>
        </div>
        <div class="time-row">
          <span class="time-label">时间</span>
          <input type="range" v-model.number="time" min="5" max="60" step="5" class="time-slider" />
          <span class="time-val">{{ time }} 分钟</span>
        </div>
        <button class="btn primary big" @click="doIso" :disabled="store.loading">生成生活圈</button>
        <div class="ck-row">
          <label><input type="checkbox" v-model="showRoads" @change="toggleRoads" /> 路网</label>
          <label><input type="checkbox" v-model="showPoints" /> 点云</label>
          <label><input type="checkbox" v-model="showFacilities" /> 设施</label>
          <button class="link-btn" @click="clearAll">清空</button>
        </div>
        <div class="hint mode-hint">勾选多种方式 → 生成不同颜色范围线同图对比</div>
      </section>

      <!-- 结果 (合并到左侧面板, 减少视线移动) -->
      <section class="sec">
        <div class="sec-title">结果</div>
        <div class="tabs">
        <button class="tab" :class="{ active: rightTab === 'stats' }" @click="rightTab = 'stats'">设施统计</button>
        <button class="tab" :class="{ active: rightTab === 'score' }" @click="rightTab = 'score'">宜居评分</button>
        <button class="tab" :class="{ active: rightTab === 'reverse' }" @click="rightTab = 'reverse'">反算选址</button>
        <button class="tab" :class="{ active: rightTab === 'curve' }" @click="rightTab = 'curve'; loadCurve()">覆盖率曲线</button>
      </div>

      <div class="tab-body">
        <!-- 设施统计 -->
        <template v-if="rightTab === 'stats'">
          <div v-if="resultModes.length" class="mode-chips">
            <div v-for="rm in resultModes" :key="rm.m"
                 :class="['mode-chip', { active: rm.m === viewedMode, off: !isModeVisible(rm.m) }]">
              <span class="chip-check" @click="toggleModeVisible(rm.m)"
                    :title="isModeVisible(rm.m) ? '隐藏该方式缓冲区' : '显示该方式缓冲区'">
                <span class="ckbox">{{ isModeVisible(rm.m) ? '✓' : '' }}</span>
              </span>
              <span class="chip-main" @click="setViewedMode(rm.m)" :title="'查看 ' + rm.label + ' 的统计/评分'">
                <span class="chip-dot" :style="{ background: rm.color }"></span>{{ rm.label }}
              </span>
            </div>
          </div>
          <StatsPanel :stats="stats" />
        </template>

        <!-- 宜居评分: 权重+按钮+卡片 同屏 (评分固定步行15分钟, 无需模式选择) -->
        <div v-else-if="rightTab === 'score'">
          <div class="score-tools">
            <div class="weight-grid">
              <div class="weight-row" v-for="(v, k) in weights" :key="k">
                <span class="w-label">{{ labelOf(k) }}</span>
                <input type="range" min="0" max="2" step="0.1" v-model.number="weights[k]" class="w-slider" />
                <span class="w-val">{{ Number(weights[k]).toFixed(1) }}</span>
              </div>
            </div>
            <div class="row">
              <span class="w-label">家庭</span>
              <select v-model="family" class="grow">
                <option value="none">无</option>
                <option value="elderly">有老人</option>
                <option value="child">有小孩</option>
                <option value="elderly+child">老人+小孩</option>
              </select>
              <button class="btn primary" @click="runScore()" :disabled="store.loading">评分</button>
            </div>
            <div class="hint" v-if="score">调整权重或家庭后自动重新评分</div>
          </div>
          <ScoreCard :score="score" :loading="scoreLoading" />
        </div>

        <!-- 覆盖率-时间曲线 -->
        <div v-else-if="rightTab === 'curve'">
          <div class="hint" v-if="!activePoint || !viewedMode">请先生成生活圈，再查看覆盖率随时间衰减曲线。</div>
          <template v-else>
            <div class="mode-chips" v-if="resultModes.length">
              <div v-for="rm in resultModes" :key="rm.m"
                   :class="['mode-chip', { active: rm.m === (curveMode || viewedMode) }]">
                <span class="chip-main" @click="setCurveMode(rm.m)" :title="'查看 ' + rm.label + ' 的覆盖率曲线'">
                  <span class="chip-dot" :style="{ background: rm.color }"></span>{{ rm.label }}
                </span>
              </div>
            </div>
            <div class="hint" style="margin-bottom:6px">
              从 <b>{{ activePoint.address || activePoint.lat.toFixed(4) + ',' + activePoint.lng.toFixed(4) }}</b>
              出发 · <b>{{ MODE_LABEL[curveMode || viewedMode] }}</b>
              <span v-if="curveLoading"> 计算中…</span>
            </div>
            <ChartBox :option="curveOption" height="230px"
                      :empty-text="curveLoading ? '计算中…' : '暂无数据，请先生成生活圈'" />
            <div class="hint" v-if="curve && curve.points">
              人口覆盖：5min {{ (curve.points[0]?.covered_population || 0).toLocaleString() }} →
              {{ (curve.points[curve.points.length - 1]?.covered_population || 0).toLocaleString() }}
              （{{ curve.points[curve.points.length - 1]?.time_budget_min }}min）
            </div>
          </template>
        </div>

        <!-- 反算选址: 以分析点为设施 -->
        <div v-else-if="rightTab === 'reverse'" class="reverse-tab">
          <div class="rev-head">
            <div class="rev-title">反算选址：以<b>分析点</b>作为设施，求同时能覆盖全部设施的最优选址区</div>
            <div class="hint" style="margin-top:4px">当前分析点 <b>{{ points.length }}</b> 个（左侧「＋ 设为分析点」添加，点会显示在地图上）。按最近勾选的出行方式：<b>{{ reverseModeLabel }}</b>。</div>
          </div>
          <button class="btn primary big" @click="doReverse" :disabled="store.loading">计算覆盖 / 选址</button>
          <div v-if="lastReverse" class="rev-result">
            <div v-for="(f, i) in lastReverse.facilities" :key="i" class="rev-line">
              <span class="rev-no">{{ i + 1 }}</span> 覆盖 {{ f.reachable_origins_count }} 个起点
            </div>
            <div v-if="lastReverse.intersection" class="rev-line strong">
              ★ 最优选址：{{ lastReverse.intersection.reachable_origins_count }} 个起点 / 覆盖 {{ fmtPop(lastReverse.intersection.reachable_population) }} 人
            </div>
          </div>
        </div>
      </div>
      </section>
    </aside>

    <!-- 多地点对比 -->
    <div v-if="rightTab === 'stats' && comparePoints.length >= 2" class="compare-panel">
      <div class="cp-head">多地点对比</div>
      <table class="cp-table">
        <thead>
          <tr>
            <th></th>
            <th v-for="(p, i) in comparePoints" :key="p.id">
              <span class="cp-dot" :style="{ background: p.color }"></span>P{{ i + 1 }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in compareRows" :key="r.label">
            <td class="cp-label">{{ r.label }}</td>
            <td v-for="(v, i) in r.values" :key="i">{{ v }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div id="status" :class="{ empty: !status }">{{ status || '就绪' }}</div>
  </div>
</template>

<style scoped>
.analysis-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; z-index: 1000;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 12px; max-height: calc(100% - 90px); overflow-y: auto;
  pointer-events: auto;
}
.panel.left { left: 12px; width: 320px; }

.sec { margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
.sec:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }
.sec-title { font-weight: 600; font-size: 13px; color: var(--text-2); margin-bottom: 8px; }

.addr-box {
  background: #f6f9fc; border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 10px; margin-bottom: 8px;
}
.addr-text { font-size: 12.5px; color: var(--text); line-height: 1.45; }
.addr-coord { font-size: 11px; color: var(--text-3); font-family: Consolas, monospace; margin-top: 2px; }

.row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.row:last-child { margin-bottom: 0; }
.grow { flex: 1; min-width: 0; }

.pt-list { display: flex; flex-direction: column; gap: 4px; margin-top: 2px; }
.pt-items { display: flex; flex-direction: column; gap: 4px; max-height: 150px; overflow-y: auto; }
.pt-head { display: flex; justify-content: space-between; align-items: center; font-size: 11.5px; color: var(--text-3); margin-bottom: 2px; }
.pt-item {
  display: flex; align-items: center; gap: 7px;
  border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px;
  cursor: pointer; transition: all .15s ease;
}
.pt-item:hover { border-color: var(--primary); }
.pt-item.active { border-color: var(--primary); background: var(--primary-light); }
.pt-item.dim { opacity: .5; }
.pt-color { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; cursor: pointer; }
.pt-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.pt-name { font-size: 12px; font-weight: 600; color: var(--text); line-height: 1.35; }
.pt-addr { font-size: 11px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pt-actions { display: flex; gap: 4px; flex-shrink: 0; }

.hint { color: var(--text-3); font-size: 11.5px; line-height: 1.5; }
.mode-hint { margin-top: 6px; }

.mode-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; margin-bottom: 8px; }
.mode-btn {
  border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 7px; padding: 6px 0; font-size: 12.5px; cursor: pointer;
  transition: all .15s ease; white-space: nowrap;
}
.mode-btn:hover { border-color: var(--primary); color: var(--primary); }
.mode-btn.active { color: #fff; font-weight: 600; }

.time-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.time-label { color: var(--text-2); font-size: 12px; width: 32px; }
.time-slider { flex: 1; accent-color: var(--primary); }
.time-val { font-size: 12px; color: var(--primary-dark); font-weight: 600; width: 54px; text-align: right; }

.btn { border: 1px solid var(--border); background: #fff; color: var(--text); padding: 6px 12px; border-radius: 8px; font-size: 12.5px; cursor: pointer; transition: all .15s ease; }
.btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); color: #fff; }
.btn.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.big { width: 100%; padding: 9px 12px; font-size: 14px; font-weight: 600; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.link-btn { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 12px; padding: 0; }
.link-btn:hover { text-decoration: underline; }

.ck-row { display: flex; gap: 12px; align-items: center; margin-top: 8px; }
.ck-row label { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2); font-size: 12px; }

.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 10px; }
.tab { border: none; background: none; padding: 6px 12px; font-size: 13px; color: var(--text-2); border-bottom: 2px solid transparent; cursor: pointer; }
.tab:hover { color: var(--primary); }
.tab.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }
.tab-body { overflow-y: auto; max-height: calc(100vh - 340px); min-height: 200px; }

.mode-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }
.mode-chip {
  display: inline-flex; align-items: center; gap: 5px;
  border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 14px; padding: 3px 9px 3px 5px; font-size: 12px;
}
.mode-chip.active { border-color: var(--primary); color: var(--primary-dark); background: var(--primary-light); }
.mode-chip.off { opacity: .45; }
.mode-chip .chip-check { display: inline-flex; align-items: center; cursor: pointer; }
.mode-chip .ckbox {
  width: 14px; height: 14px; border: 1px solid var(--border); border-radius: 3px;
  background: #fff; color: #fff; font-size: 11px; line-height: 1;
  display: inline-flex; align-items: center; justify-content: center;
}
.mode-chip:not(.off) .ckbox { background: var(--primary); border-color: var(--primary); }
.mode-chip .chip-main { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
.mode-chip .chip-dot { width: 8px; height: 8px; border-radius: 50%; }

.score-tools { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.weight-grid { display: grid; grid-template-columns: 1fr; row-gap: 5px; margin-bottom: 7px; }
.weight-row { display: flex; align-items: center; gap: 8px; }
.w-label { width: 34px; color: var(--text-2); font-size: 12px; }
.w-slider { flex: 1; min-width: 0; accent-color: var(--primary); }
.w-val { width: 26px; text-align: right; color: var(--primary-dark); font-weight: 600; font-size: 12px; }

.reverse-tab .rev-head { margin-bottom: 8px; }
.rev-title { font-size: 12px; color: var(--text-2); margin-bottom: 6px; line-height: 1.5; }
.rev-result { margin-top: 10px; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
.rev-line { font-size: 12px; color: var(--text-2); display: flex; align-items: center; gap: 6px; }
.rev-no { width: 18px; height: 18px; border-radius: 50%; background: var(--primary); color: #fff; font-size: 11px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
.rev-line.strong { color: #2e7d32; font-weight: 600; }

.compare-panel {
  position: fixed; right: 12px; bottom: 52px; z-index: 1500; width: 340px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 10px 12px;
  pointer-events: auto;
}
.cp-head { font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.cp-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.cp-table th, .cp-table td { padding: 4px 6px; text-align: center; border-bottom: 1px solid var(--border); }
.cp-table th { color: var(--text-2); font-weight: 600; }
.cp-table td.cp-label { text-align: left; color: var(--text-2); white-space: nowrap; }
.cp-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; }

#status {
  position: fixed; left: 12px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 55%; transition: opacity .3s;
}
#status.empty { opacity: .55; }
</style>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { store } from '../store'
import { clearOverlays, drawHexGrid, scoreRamp, classBreaksColor, setPickMode, setCurrentPoint, clearCurrentPoint } from '../mapLayers'

const status = ref('就绪')
const centerLat = ref(store.pointLat)
const centerLng = ref(store.pointLng)
const radiusKm = ref(5)
const gridType = ref('square')
const cellSize = ref(0.005)
const metric = ref('score')
const category = ref('supermarket')
const picking = ref(false)
// 图例分级区间 (用户可改, 逗号分隔)
const breaksText = ref('0,20,40,60,80,100')
let customBreaks = false

const CATS = [
  { v: 'supermarket', l: '超市' }, { v: 'hospital', l: '医院' }, { v: 'pharmacy', l: '药店' },
  { v: 'park', l: '公园' }, { v: 'mall', l: '商场' }, { v: 'school_primary', l: '小学' },
  { v: 'kindergarten', l: '幼儿园' }, { v: 'sports', l: '体育' }, { v: 'street_commercial', l: '商业街' },
]
const CELL_PRESETS = [
  { v: 0.002, l: '200m' },
  { v: 0.005, l: '500m' },
  { v: 0.01, l: '1km' },
]

// 值键: score 指标用 score, density 指标用 density
const valueKey = computed(() => (metric.value === 'density' ? 'density' : 'score'))
// 解析用户输入的区间 (升序)
const breaks = computed(() => {
  const arr = breaksText.value.split(/[,，\s]+/).map((x) => parseFloat(x)).filter((n) => !isNaN(n))
  arr.sort((a, b) => a - b)
  if (arr.length < 2) return [0, 100]
  return arr
})

const fmt = (v) => (metric.value === 'density' ? Number(v).toFixed(1) : String(Math.round(v)))

function currentBBox() {
  const dLat = radiusKm.value / 111.32
  const dLng = radiusKm.value / (111.32 * Math.cos((centerLat.value * Math.PI) / 180))
  return [centerLng.value - dLng, centerLat.value - dLat, centerLng.value + dLng, centerLat.value + dLat]
}

async function loadGrid() {
  const bbox = currentBBox()
  const est = ((bbox[2] - bbox[0]) / cellSize.value) * ((bbox[3] - bbox[1]) / cellSize.value)
  if (est > 20000) {
    status.value = `网格数量过大(${Math.round(est)} > 20000), 请缩小半径或增大网格`
    return
  }
  status.value = '计算网格统计…'
  const r = await api.grid(bbox, cellSize.value, metric.value, metric.value === 'density' ? category.value : null, gridType.value)
  if (!r.ok) { status.value = `网格失败: ${r.data.error || r.status}`; return }
  // 设施密度: 未手动改区间时, 用实际数据分布自动定区间
  if (metric.value === 'density' && !customBreaks) {
    const ds = r.data.features.map((f) => f.properties.density || 0)
    const max = Math.max(...ds) || 1
    const steps = [0, 0.25, 0.5, 0.75, 0.9, 1].map((k) => +(max * k).toFixed(metric.value === 'density' ? 1 : 0))
    breaksText.value = [...new Set(steps)].join(',')
  }
  const colorFn = (props) => classBreaksColor(breaks.value)(props[valueKey.value])
  clearOverlays()
  drawHexGrid(r.data, colorFn)
  const scores = r.data.features.map((f) => f.properties[valueKey.value])
  let extra = ''
  if (metric.value === 'density' && r.data.meta.density_caps) {
    const cap = r.data.meta.density_caps[category.value]
    const catL = (CATS.find((c) => c.v === category.value) || {}).l || category.value
    extra = ` | ${catL} 达标线 ${cap}/km²`
  }
  status.value = `${r.data.meta.n_cells} 格 (${r.data.meta.grid_type})${extra} | ${valueKey.value === 'density' ? '密度' : '评分'} ${scores.length ? Math.min(...scores).toFixed(1) : 0} ~ ${scores.length ? Math.max(...scores).toFixed(1) : 0}`
  updateLegend()
}

// 图例: 按当前用户区间生成
function updateLegend() {
  const legend = document.getElementById('grid-legend')
  if (!legend) return
  if (!breaksText.value.trim()) {
    legend.innerHTML = '<div class="lrow"><span class="ltxt">设施密度：生成后按数据自动分档（也可在输入框手动指定）</span></div>'
    return
  }
  const b = breaks.value
  const n = b.length - 1
  legend.innerHTML = b.slice(0, -1).map((lo, i) => {
    const hi = b[i + 1]
    const label = i === n - 1 ? `≥ ${fmt(lo)}` : `${fmt(lo)} ~ ${fmt(hi)}`
    return `<div class="lrow"><span class="swatch" style="background:${scoreRamp((100 * (i + 0.5)) / n)}"></span><span class="ltxt">${label}</span></div>`
  }).join('')
}

// 切换指标时重置默认区间 (用户可再改)
function onMetricChange() {
  customBreaks = false
  // 设施密度: 静态默认无意义, 用空=自动分档 (生成后回填真实分档)
  breaksText.value = metric.value === 'density' ? '' : '0,20,40,60,80,100'
  updateLegend()
}
watch(metric, onMetricChange)

// 中心点标记: 进入分级色彩 Tab 时显示, 离开时清除
watch(() => store.activeTab, (v) => {
  if (v === 'choropleth') {
    setCurrentPoint(centerLat.value, centerLng.value, '中心点')
  } else {
    clearCurrentPoint()
  }
})
// 中心点变化 (选点) 时更新标记
watch([centerLat, centerLng], () => {
  if (store.activeTab === 'choropleth') {
    setCurrentPoint(centerLat.value, centerLng.value, '中心点')
  }
})

function onBreaksInput() {
  customBreaks = true
  updateLegend()
}

// 在地图上选中心点
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
onBeforeUnmount(() => {
  exitPick()
  clearCurrentPoint()
})
onMounted(updateLegend)
</script>

<template>
  <div class="choropleth-view">
    <aside class="panel">
      <div class="title">分级色彩 · 区域网格统计</div>

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
        <input type="range" min="1" max="12" step="0.5" v-model.number="radiusKm" class="grow" />
        <span class="val">{{ radiusKm }} km</span>
      </div>
      <div class="row">
        <span class="lbl">网格</span>
        <select v-model="gridType" class="grow">
          <option value="square">四边形</option>
          <option value="hex">六边形</option>
        </select>
      </div>
      <div class="row">
        <span class="lbl">尺寸</span>
        <div class="presets">
          <button v-for="p in CELL_PRESETS" :key="p.v"
                  :class="['preset', { active: cellSize === p.v }]"
                  @click="cellSize = p.v">{{ p.l }}</button>
        </div>
      </div>
      <div class="row">
        <select v-model="metric" class="grow">
          <option value="score">综合宜居评分</option>
          <option value="density">设施密度</option>
        </select>
        <select v-if="metric === 'density'" v-model="category" class="grow">
          <option v-for="c in CATS" :key="c.v" :value="c.v">{{ c.l }}</option>
        </select>
      </div>
      <div class="row">
        <span class="lbl">图例</span>
        <input type="text" class="grow" v-model="breaksText" @input="onBreaksInput"
               :placeholder="valueKey === 'density' ? '自动分档(逗号分隔可自定义)' : '0,20,40,60,80,100'"
               :title="valueKey === 'density' ? '密度分级区间, 逗号分隔, 留空=自动' : '评分分级区间, 逗号分隔'" />
        <button class="btn" @click="customBreaks = false; onMetricChange(); loadGrid()">重置</button>
      </div>
      <div class="row">
        <button class="btn primary grow" @click="loadGrid">生成</button>
        <button class="btn" @click="clearOverlays">清空</button>
      </div>

      <div id="grid-legend" class="legend"></div>
      <div class="hint">
        图例区间可自行输入(逗号分隔)后点「生成」生效；点「重置」恢复该指标的默认区间。<br />
        综合宜居评分默认按 0~100；设施密度按实际数据分布自动分档(也可手改)。各类设施达标线不同：医院 0.8/km²、药店 5/km²、小学 1.5/km² 等。颜色：红=低 → 绿=高。
      </div>
    </aside>
    <div id="status">{{ status }}</div>
  </div>
</template>

<style scoped>
.choropleth-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; left: 12px; z-index: 1000; width: 272px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px;
  pointer-events: auto;
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
}
.preset:hover { border-color: var(--primary); color: var(--primary); }
.preset.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn { border: 1px solid var(--border); background: #fff; color: var(--text); padding: 5px 10px; border-radius: 8px; font-size: 12.5px; cursor: pointer; }
.btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); color: #fff; }
.btn.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.legend { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.hint { color: var(--text-3); font-size: 11.5px; line-height: 1.6; }
#status {
  position: fixed; left: 120px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 55%;
}
</style>

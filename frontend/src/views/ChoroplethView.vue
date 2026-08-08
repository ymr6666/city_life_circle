<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { store } from '../store'
import { clearOverlays, drawHexGrid, scoreRamp } from '../mapLayers'

const status = ref('就绪')
const cellSize = ref(0.005)
const metric = ref('score')
const category = ref('supermarket')

const CELL_PRESETS = [
  { v: 0.01, l: '1km' },
  { v: 0.005, l: '500m' },
  { v: 0.0025, l: '250m' },
]

const CATS = [
  { v: 'supermarket', l: '超市' }, { v: 'hospital', l: '医院' }, { v: 'pharmacy', l: '药店' },
  { v: 'park', l: '公园' }, { v: 'mall', l: '商场' }, { v: 'school_primary', l: '小学' },
  { v: 'kindergarten', l: '幼儿园' }, { v: 'sports', l: '体育' }, { v: 'street_commercial', l: '商业街' },
]

function currentBBox() {
  const b = store.map.getBounds()
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
}

async function loadGrid() {
  status.value = '计算六边形网格...'
  const r = await api.grid(currentBBox(), cellSize.value, metric.value, metric.value === 'density' ? category.value : null)
  if (!r.ok) { status.value = `网格失败: ${r.data.error || r.status}`; return }
  clearOverlays()
  drawHexGrid(r.data, scoreRamp)
  const scores = r.data.features.map((f) => f.properties.score)
  status.value = `${r.data.meta.n_cells} 格 | 评分 ${scores.length ? Math.min(...scores).toFixed(1) : 0} ~ ${scores.length ? Math.max(...scores).toFixed(1) : 0}`
  updateLegend(r.data)
}

function updateLegend(fc) {
  const legend = document.getElementById('grid-legend')
  if (!legend) return
  const samples = [0, 20, 40, 60, 80, 100]
  legend.innerHTML = samples
    .map((v) => `<div class="lrow"><span class="swatch" style="background:${scoreRamp(v)}"></span>${v}</div>`)
    .join('')
}
</script>

<template>
  <div class="choropleth-view">
    <aside class="panel">
      <div class="title">分级色彩 · 六边形网格</div>
      <div class="row">
        <label>网格大小</label>
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
        <button class="btn primary grow" @click="loadGrid">生成</button>
        <button class="btn" @click="clearOverlays">清空</button>
      </div>
      <div id="grid-legend" class="legend"></div>
      <div class="hint">网格随当前地图视野生成，拖动/缩放后点"生成"刷新。</div>
    </aside>
    <div id="status">{{ status }}</div>
  </div>
</template>

<style scoped>
.choropleth-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; left: 12px; z-index: 1000; width: 240px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px;
  pointer-events: auto;
}
.title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.row { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.row label { color: var(--text-2); font-size: 12px; white-space: nowrap; }
.grow { flex: 1; min-width: 0; }
.presets { display: flex; gap: 4px; flex: 1; }
.preset {
  flex: 1; border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 6px; padding: 3px 0; font-size: 11.5px; cursor: pointer;
}
.preset:hover { border-color: var(--primary); color: var(--primary); }
.preset.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.legend { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.lrow { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); }
.swatch { width: 34px; height: 12px; border-radius: 2px; border: 1px solid rgba(0,0,0,.08); }
.hint { color: var(--text-3); font-size: 12px; }
#status {
  position: fixed; left: 12px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 55%;
}
</style>

<script setup>
import { ref, computed } from 'vue'
import { store, togglePopLayer } from '../store'
import { popRamp, rampLegend } from '../mapLayers'

const status = ref('就绪')
const enabled = computed(() => store.popOn)

// 瓦片色阶阈值 (人/格 ≈ 0.008km²), 与 scripts/utils/build_pop_tiles.py 一致
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

updateLegend()
</script>

<template>
  <div class="pop-view">
    <aside class="panel">
      <div class="title">人口分布 · 100m 栅格</div>

      <div class="row">
        <button class="btn primary grow" @click="toggle">
          {{ enabled ? '关闭人口密度图层' : '开启人口密度图层' }}
        </button>
      </div>
      <div class="row">
        <button class="btn grow" @click="fitHefei">定位合肥全域</button>
      </div>

      <div id="pop-legend" class="legend"></div>

      <div class="hint">
        <b>预渲染栅格底图</b>：WorldPop 2020 100m 人口栅格重投影+赋色切瓦片，
        任意缩放级别直接可用，无需重新计算。<br />
        地图左下角「人口密度」按钮与这里同步开关。
      </div>
    </aside>
    <div id="status">{{ status }}</div>
  </div>
</template>

<style scoped>
.pop-view { position: absolute; inset: 0; pointer-events: none; }
.panel {
  position: absolute; top: 64px; left: 12px; z-index: 1000; width: 250px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px;
  pointer-events: auto;
}
.title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.btn { border: 1px solid var(--border); background: #fff; color: var(--text); padding: 6px 10px; border-radius: 8px; font-size: 12.5px; cursor: pointer; }
.btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); color: #fff; }
.grow { flex: 1; min-width: 0; }
.legend { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.lrow { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); }
.swatch { width: 30px; height: 12px; border-radius: 2px; border: 1px solid rgba(0,0,0,.08); flex-shrink: 0; }
.ltxt { white-space: nowrap; }
.hint { color: var(--text-3); font-size: 11.5px; line-height: 1.7; }
.hint b { color: var(--primary-dark); }
#status {
  position: fixed; left: 12px; bottom: 12px; z-index: 2000;
  background: rgba(38, 50, 56, .82); color: #fff; padding: 5px 12px;
  border-radius: 6px; font-size: 12px; max-width: 55%;
}
</style>

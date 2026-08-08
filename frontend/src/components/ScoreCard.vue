<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  score: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const radarEl = ref(null)
let chart = null

function ensureChart() {
  if (chart) return chart
  if (!radarEl.value) return null
  try {
    chart = echarts.init(radarEl.value)
  } catch (e) {
    return null
  }
  return chart
}

function gradeClass(g) {
  return { 优: 'g-good', 良: 'g-mid', 中: 'g-low', 差: 'g-bad' }[g] || 'g-mid'
}

function render() {
  const ch = ensureChart()
  if (!ch || !props.score || !props.score.sub_scores) return
  const dims = Object.values(props.score.sub_scores)
  ch.setOption({
    tooltip: { trigger: 'item' },
    radar: {
      indicator: dims.map((d) => ({ name: d.label, max: 100 })),
      radius: '68%',
      axisName: { color: '#607d8b', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e0e6ec' } },
      splitArea: { areaStyle: { color: ['#fff', '#f6f9fc'] } },
      axisLine: { lineStyle: { color: '#d6dee6' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: dims.map((d) => d.score),
        name: '生活圈评分',
        areaStyle: { color: 'rgba(25,118,210,0.25)' },
        lineStyle: { color: '#1976d2', width: 2 },
        itemStyle: { color: '#1976d2' },
      }],
    }],
  })
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (chart) chart.dispose()
})
function resize() { if (chart) chart.resize() }
// 评分数据出现后再初始化图表 (radarEl 此时才挂载), 并等待 DOM 布局
watch(() => props.score, (v) => {
  if (v) setTimeout(() => render(), 0)
  else render()
}, { deep: true })

function fmtPop(p) {
  if (p == null) return '—'
  return p >= 10000 ? (p / 10000).toFixed(1) + '万' : String(p)
}
function factText(d) {
  const f = d.facts || {}
  if (d.label === '交通') {
    const c = f.categories || {}
    const metro = c.metro != null ? c.metro : '—'
    const bus = c.bus != null ? c.bus : '—'
    const nd = f.nearest_distance_m != null ? `${Math.round(f.nearest_distance_m)}m` : '—'
    return `附近 ${metro} 地铁站 · ${bus} 公交站 | 最近站 ${nd}`
  }
  const cnt = f.weighted_count
  const nd = f.nearest_distance_m != null ? `${Math.round(f.nearest_distance_m)}m` : '—'
  return `${d.label}可达 ${cnt} 处 | 最近 ${nd}`
}
const DIM_LABEL = { medical: '医疗', education: '教育', shopping: '购物', leisure: '休闲', transit: '交通' }
function labelOf(k) { return DIM_LABEL[k] || k }
function familyLabel(f) {
  return { elderly: '有老人', child: '有小孩', 'elderly+child': '老人+小孩' }[f] || '无'
}
</script>

<template>
  <div class="score-card">
    <div v-if="loading" class="score-loading">评分计算中…</div>

    <template v-else-if="score">
      <div class="total">
        <div class="grade-row">
          <span class="grade" :class="gradeClass(score.grade)">{{ score.grade }}</span>
          <span class="grade-desc">{{ score.grade_desc }}</span>
        </div>
        <div class="num" :class="scoreColor(score.score)">{{ score.score }}</div>
        <div class="unit">综合宜居分 / 100</div>
      </div>

      <div class="facts-strip">
        <div class="fact-item"><b>{{ fmtPop(score.population) }}</b> 覆盖人口</div>
        <div class="fact-item" v-if="score.population_density_per_km2 != null"><b>{{ Math.round(score.population_density_per_km2).toLocaleString() }}</b> 人/km²</div>
        <div class="fact-item" v-if="score.area_km2 != null"><b>{{ score.area_km2 }}</b> km²</div>
        <div class="fact-item" v-if="score.reachable_pois_count != null"><b>{{ score.reachable_pois_count }}</b> 可达POI</div>
      </div>

      <div ref="radarEl" class="radar"></div>

      <div class="dims">
        <div v-for="d in Object.values(score.sub_scores || {})" :key="d.label" class="dim">
          <span class="label">{{ d.label }}</span>
          <span class="val" :class="scoreColor(d.score)">{{ d.score }}</span>
          <div class="bar"><div class="fill" :style="{ width: d.score + '%' }"></div></div>
          <span class="fact" v-if="d.facts">{{ factText(d) }}</span>
        </div>
      </div>

      <div class="weight-info" v-if="score.weight_info">
        <span class="chip">家庭：{{ familyLabel(score.weight_info.family) }}</span>
        <template v-for="(v, k) in score.weight_info.user_weights" :key="k">
          <span class="chip" v-if="v !== 1">{{ labelOf(k) }}×{{ v }}</span>
        </template>
      </div>
    </template>

    <div v-else class="empty">
      点击「宜居评分」生成生活圈评分卡<br />
      <span class="empty-sub">评分由医疗 / 教育 / 购物 / 休闲 / 交通 五维构成</span>
    </div>
  </div>
</template>

<script>
export default {
  methods: {
    scoreColor(v) {
      if (v >= 85) return 'good'
      if (v >= 70) return 'mid'
      if (v >= 55) return 'ok'
      return 'low'
    },
  },
}
</script>

<style scoped>
.score-card { display: flex; flex-direction: column; gap: 8px; }
.score-loading { text-align: center; color: var(--text-3); padding: 30px 0; }
.total { text-align: center; padding: 6px 0 2px; }
.grade-row { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 2px; }
.grade {
  font-size: 20px; font-weight: 700; padding: 1px 14px; border-radius: 20px; color: #fff;
}
.g-good { background: #2e7d32; }
.g-mid { background: #558b2f; }
.g-low { background: #f57c00; }
.g-bad { background: #c62828; }
.grade-desc { font-size: 12px; color: var(--text-3); }
.total .num { font-size: 44px; font-weight: 700; line-height: 1.05; }
.total .unit { color: var(--text-3); font-size: 12px; }
.facts-strip {
  display: flex; gap: 14px; flex-wrap: wrap; justify-content: center;
  padding: 7px 10px; background: #f6f9fc; border-radius: 8px;
}
.fact-item { color: var(--text-2); font-size: 12px; }
.fact-item b { color: var(--primary-dark); font-size: 14px; margin-right: 2px; }
.radar { height: 210px; }
.dims { display: flex; flex-direction: column; gap: 7px; }
.dim { display: grid; grid-template-columns: 44px 34px 1fr; align-items: center; gap: 8px; }
.dim .label { color: var(--text-2); }
.dim .val { font-weight: 700; text-align: right; }
.dim .bar { height: 6px; background: #eef2f6; border-radius: 3px; overflow: hidden; }
.dim .fill { height: 100%; background: var(--primary); border-radius: 3px; }
.dim .fact { grid-column: 1 / -1; color: var(--text-3); font-size: 11px; }
.weight-info { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; color: var(--text-3); font-size: 11px; }
.chip { background: var(--primary-light); color: var(--primary-dark); border-radius: 4px; padding: 1px 6px; }
.empty { color: var(--text-3); text-align: center; padding: 30px 0; line-height: 1.9; }
.empty-sub { font-size: 11px; }
.good { color: #2e7d32; }
.mid { color: #558b2f; }
.ok { color: #f57c00; }
.low { color: #c62828; }
</style>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: { type: Object, default: null },
  height: { type: String, default: '200px' },
  emptyText: { type: String, default: '暂无数据' },
})

const el = ref(null)
let chart = null

function ensureChart() {
  if (chart) return chart
  if (!el.value) return null
  try { chart = echarts.init(el.value) } catch (e) { return null }
  return chart
}

function render() {
  const ch = ensureChart()
  if (!ch) return
  if (!props.option) {
    ch.clear()
    return
  }
  // 容器由隐藏→显示/尺寸变化后需重算, 否则沿用 init 时的尺寸导致图表被压缩
  ch.resize()
  try { ch.setOption(props.option, true) } catch (e) { /* 忽略渲染错误 */ }
}

onMounted(() => {
  render()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (chart) { chart.dispose(); chart = null }
})
function onResize() { if (chart) chart.resize() }

watch(() => props.option, (v) => {
  if (v) setTimeout(() => render(), 0)
  else render()
}, { deep: true })
</script>

<template>
  <div class="chart-box">
    <div ref="el" class="chart" :style="{ height }" v-show="option"></div>
    <div v-if="!option" class="empty">{{ emptyText }}</div>
  </div>
</template>

<style scoped>
.chart-box { width: 100%; }
.chart { width: 100%; }
.empty { color: var(--text-3); text-align: center; font-size: 12px; padding: 24px 0; }
</style>

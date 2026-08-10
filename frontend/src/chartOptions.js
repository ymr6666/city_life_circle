// ECharts 图表配置生成器 (统一配色/风格, 与 App 主题一致)

const AXIS_COLOR = '#607d8b'
const SPLIT_LINE = '#e0e6ec'
const PRIM = '#1976d2'
const RED = '#d32f2f'
const GREEN = '#2e7d32'
const ORANGE = '#f57c00'
const AMBER = '#f9a825'

const baseTooltip = {
  trigger: 'axis',
  backgroundColor: 'rgba(255,255,255,0.96)',
  borderColor: SPLIT_LINE,
  textStyle: { color: '#263238', fontSize: 12 },
  confine: true,
}

function baseGrid(extra = {}) {
  return {
    left: 8, right: 16, top: 30, bottom: 8, containLabel: true,
    ...extra,
  }
}

function baseXAxis(data, extra = {}) {
  return {
    type: 'category', data,
    axisLine: { lineStyle: { color: AXIS_COLOR } },
    axisTick: { show: false },
    axisLabel: { color: AXIS_COLOR, fontSize: 11 },
    ...extra,
  }
}

function baseYAxis(extra = {}) {
  return {
    type: 'value',
    axisLabel: { color: AXIS_COLOR, fontSize: 11 },
    splitLine: { lineStyle: { color: SPLIT_LINE, type: 'dashed' } },
    ...extra,
  }
}

// 覆盖率/设施数 - 时间衰减曲线 (等时圈多次调用)
// 人口与设施量级差异大, 用双坐标轴: 左轴=人口, 右轴=设施
export function decayLineOption({ x, series, unit = '' }) {
  // series: [{name, data:[...], color, yAxisIndex}]
  const hasSecondAxis = series.some((s) => s.yAxisIndex === 1)
  return {
    tooltip: { ...baseTooltip, valueFormatter: (v) => (v == null ? '—' : Number(v).toLocaleString()) },
    legend: { top: 0, textStyle: { color: AXIS_COLOR, fontSize: 11 }, icon: 'roundRect', itemWidth: 12, itemHeight: 6 },
    grid: baseGrid({ right: hasSecondAxis ? 8 : 16, top: 24 }),
    xAxis: baseXAxis(x, { name: '时间(min)', nameTextStyle: { color: AXIS_COLOR, fontSize: 11 } }),
    yAxis: [
      baseYAxis({
        axisLine: { show: true, lineStyle: { color: series[0]?.color || PRIM } },
        axisLabel: { color: series[0]?.color || PRIM, fontSize: 11 },
      }),
      ...(hasSecondAxis ? [baseYAxis({
        axisLine: { show: true, lineStyle: { color: series[1]?.color || ORANGE } },
        axisLabel: { color: series[1]?.color || ORANGE, fontSize: 11 },
        splitLine: { show: false },
      })] : []),
    ],
    series: series.map((s) => ({
      name: s.name, type: 'line', smooth: true,
      data: s.data,
      yAxisIndex: s.yAxisIndex || 0,
      symbolSize: 5,
      lineStyle: { width: 2.5, color: s.color || PRIM },
      itemStyle: { color: s.color || PRIM },
      areaStyle: s.area ? { color: s.color || PRIM, opacity: 0.08 } : undefined,
    })),
  }
}

function compactNum(v) {
  if (v == null) return ''
  const n = Number(v)
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(Math.round(n))
}

// 选址多方案对比 (现状 / 新建1座 / 新建2座 / ...)
// 左轴=累计覆盖人口(柱), 右轴=本轮新增人口(线) —— 量级差异大, 双轴
export function schemeCompareOption({ items }) {
  // items: [{name, coverage_population, incremental_population, coverage_rate}]
  return {
    tooltip: {
      ...baseTooltip, trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const it = items[params[0].dataIndex] || {}
        const rate = it.coverage_rate ? ` · 覆盖率 <b>${(it.coverage_rate * 100).toFixed(1)}%</b>` : ''
        return `${params[0].axisValue}<br/>` +
          params.map((p) => `${p.marker}${p.seriesName}: <b>${Number(p.value).toLocaleString()}</b>${p.seriesName.startsWith('累计') ? rate : ''}`).join('<br/>')
      },
    },
    legend: { top: 0, textStyle: { color: AXIS_COLOR, fontSize: 11 }, icon: 'roundRect', itemWidth: 12, itemHeight: 6 },
    grid: baseGrid({ right: 8, top: 24 }),
    xAxis: baseXAxis(items.map((i) => i.name), { name: '方案', nameTextStyle: { color: AXIS_COLOR, fontSize: 11 } }),
    yAxis: [
      baseYAxis({
        axisLine: { show: true, lineStyle: { color: PRIM } },
        axisLabel: { color: PRIM, fontSize: 11 },
      }),
      baseYAxis({
        axisLine: { show: true, lineStyle: { color: ORANGE } },
        axisLabel: { color: ORANGE, fontSize: 11 },
        splitLine: { show: false },
      }),
    ],
    series: [
      {
        name: '累计覆盖人口', type: 'bar', yAxisIndex: 0, barWidth: '42%',
        data: items.map((i) => i.coverage_population),
        itemStyle: { color: PRIM, borderRadius: [3, 3, 0, 0] },
        label: { show: true, position: 'top', color: '#455a64', fontSize: 10, formatter: (p) => compactNum(p.value) },
      },
      {
        name: '本轮新增人口', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 6,
        data: items.map((i) => i.incremental_population),
        lineStyle: { color: ORANGE, width: 2.5 }, itemStyle: { color: ORANGE },
      },
    ],
  }
}

// 搬迁/关闭净影响瀑布图
// items: [{name, value, type:'base'|'add'|'sub'}]
export function waterfallOption({ title, items, color } = {}) {
  const names = items.map((i) => i.name)
  const values = items.map((i) => i.value)
  // 瀑布: 累计起点 (base 为绝对, add/sub 从累计累加)
  const start = []
  let acc = 0
  items.forEach((i) => {
    start.push(acc)
    acc += i.value
  })
  const colors = items.map((i) =>
    i.type === 'add' ? GREEN : i.type === 'sub' ? RED : (color || AMBER))
  return {
    tooltip: { ...baseTooltip, trigger: 'item', valueFormatter: (v) => Number(v || 0).toLocaleString() },
    title: title ? { text: title, left: 'center', top: 0, textStyle: { fontSize: 13, color: '#263238', fontWeight: 600 } } : undefined,
    grid: baseGrid({ top: title ? 40 : 30 }),
    xAxis: baseXAxis(names),
    yAxis: baseYAxis(),
    series: [{
      type: 'bar',
      data: items.map((it, i) => ({
        value: it.value,
        itemStyle: {
          color: colors[i],
          borderColor: colors[i],
          borderWidth: 0,
          borderRadius: [3, 3, 0, 0],
        },
      })),
      // 用透明堆叠实现瀑布累计效果
      stack: 'wf',
      label: {
        show: true, position: 'top',
        formatter: (p) => (p.value === 0 ? '' : Number(p.value).toLocaleString()),
        color: '#455a64', fontSize: 11,
      },
    }, {
      type: 'bar',
      data: items.map((i) => ({ value: 0, itemStyle: { color: 'transparent' } })),
      stack: 'wf',
    }],
  }
}

// 关闭影响组成条形 (受影响=退级+完全失去)
export function stackedBarOption({ title, items }) {
  // items: [{name, downgraded, lost}]
  return {
    tooltip: { ...baseTooltip, trigger: 'axis', valueFormatter: (v) => Number(v || 0).toLocaleString() },
    title: title ? { text: title, left: 'center', top: 0, textStyle: { fontSize: 13, color: '#263238', fontWeight: 600 } } : undefined,
    legend: { top: 0, textStyle: { color: AXIS_COLOR, fontSize: 11 } },
    grid: baseGrid({ top: title ? 40 : 30 }),
    xAxis: baseXAxis(items.map((i) => i.name)),
    yAxis: baseYAxis(),
    series: [
      {
        name: '退级', type: 'bar', stack: 'c',
        data: items.map((i) => i.downgraded),
        itemStyle: { color: AMBER },
      },
      {
        name: '完全失去', type: 'bar', stack: 'c',
        data: items.map((i) => i.lost),
        itemStyle: { color: RED },
      },
    ],
  }
}

// 选址候选评分柱状图 (横向)
export function siteBarOption({ items }) {
  // items: [{name, coverage_population, fill_population, score}]
  const names = items.map((i) => i.name)
  const fill = items.map((i) => i.fill_population)
  const cov = items.map((i) => i.coverage_population)
  return {
    tooltip: { ...baseTooltip, trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => Number(v || 0).toLocaleString() },
    legend: { top: 0, textStyle: { color: AXIS_COLOR, fontSize: 11 }, icon: 'roundRect' },
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { color: AXIS_COLOR, fontSize: 11 },
      splitLine: { lineStyle: { color: SPLIT_LINE, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: names.map((n) => (n && n.length > 6 ? n.slice(0, 6) + '…' : n)),
      axisLabel: { color: AXIS_COLOR, fontSize: 11 },
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisTick: { show: false },
    },
    series: [
      { name: '填补盲区', type: 'bar', data: fill, itemStyle: { color: RED } },
      { name: '覆盖人口', type: 'bar', data: cov, itemStyle: { color: PRIM } },
    ],
  }
}

// 多类别同阈值覆盖率对比 (条形)
export function catCoverageBarOption({ items }) {
  // items: [{name, rate}]
  return {
    tooltip: { ...baseTooltip, trigger: 'axis', valueFormatter: (v) => (v == null ? '—' : (v * 100).toFixed(1) + '%') },
    grid: baseGrid(),
    xAxis: baseXAxis(items.map((i) => i.name)),
    yAxis: { ...baseYAxis(), max: 1, axisLabel: { color: AXIS_COLOR, fontSize: 11, formatter: (v) => (v * 100) + '%' } },
    series: [{
      type: 'bar',
      data: items.map((i) => ({ value: i.rate, itemStyle: { color: i.color || PRIM, borderRadius: [3, 3, 0, 0] } })),
      barWidth: '55%',
      label: { show: true, position: 'top', formatter: (p) => (p.value * 100).toFixed(0) + '%', color: '#455a64', fontSize: 11 },
    }],
  }
}

export const CHART_COLORS = { PRIM, RED, GREEN, ORANGE, AMBER }

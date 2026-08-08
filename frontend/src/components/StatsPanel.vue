<script setup>
import { ref, computed } from 'vue'
import { CAT_LABEL, CAT_COLORS } from '../store'
import { focusFacility } from '../mapLayers'

const props = defineProps({
  stats: { type: Object, default: null },
})

const cats = computed(() => {
  if (!props.stats || !props.stats.facilities_by_category) return []
  return Object.entries(props.stats.facilities_by_category)
    .map(([cat, info]) => ({ cat, label: CAT_LABEL[cat] || cat, ...info }))
    .sort((a, b) => b.count - a.count)
})

const expandedCat = ref(null)
const expandedFac = ref(null)

const expandedFacilities = computed(() => {
  if (!expandedCat.value || !props.stats || !props.stats.facilities_by_category) return []
  const info = props.stats.facilities_by_category[expandedCat.value]
  return (info && info.items) || []
})
function labelOf(k) { return CAT_LABEL[k] || k }

function toggleCat(cat) {
  expandedCat.value = expandedCat.value === cat ? null : cat
  expandedFac.value = null
}
function toggleFac(f) {
  expandedFac.value = expandedFac.value === f ? null : f
}
function onFocusFacility(f) {
  focusFacility(f)
}

function fmtPop(p) {
  if (p == null) return '—'
  return p >= 10000 ? (p / 10000).toFixed(1) + '万' : String(p)
}
function fmtDist(m) {
  if (m == null) return ''
  return m >= 1000 ? (m / 1000).toFixed(1) + 'km' : Math.round(m) + 'm'
}

function detailRows(f) {
  const rows = []
  if (f.sub_category) rows.push({ k: '类型', v: f.sub_category })
  if (f.rating) rows.push({ k: '评分', v: `${f.rating}` })
  if (f.cost) rows.push({ k: '人均', v: `¥${f.cost}` })
  if (f.opentime_today) rows.push({ k: '营业', v: f.opentime_today })
  if (f.count > 1) rows.push({ k: '圈内同设施', v: `${f.count} 个` })
  return rows
}
</script>

<template>
  <div class="stats-panel">
    <template v-if="stats">
      <div class="summary">
        <div class="sum-item"><b>{{ stats.reachable_facilities_count ?? 0 }}</b> 设施</div>
        <div class="sum-item"><b>{{ stats.reachable_pois_count ?? 0 }}</b> POI</div>
        <div class="sum-item" v-if="stats.metro_stations != null"><b>{{ stats.metro_stations }}</b> 地铁</div>
        <div class="sum-item" v-if="stats.bus_stops != null"><b>{{ stats.bus_stops }}</b> 公交</div>
        <div class="sum-item" v-if="stats.population != null"><b>{{ fmtPop(stats.population) }}</b> 覆盖人口</div>
        <div class="sum-item" v-if="stats.population_density != null"><b>{{ Math.round(stats.population_density).toLocaleString() }}</b> 人/km²</div>
      </div>

      <div class="grid">
        <div v-for="c in cats" :key="c.cat"
             :class="['cat-card', { open: expandedCat === c.cat }]"
             @click="toggleCat(c.cat)">
          <span class="dot" :style="{ background: CAT_COLORS[c.cat] || '#607d8b' }"></span>
          <span class="name">{{ c.label }}</span>
          <span class="cnt">{{ c.count }}</span>
          <span class="caret">{{ expandedCat === c.cat ? '▾' : '▸' }}</span>
        </div>
      </div>

      <!-- 一级展开: 设施名称列表 -->
      <div v-if="expandedCat" class="fac-detail">
        <div class="detail-title">
          {{ labelOf(expandedCat) }} 设施
          <span class="detail-hint">点击条目查看详情，再点击可在地图上定位</span>
        </div>

        <!-- 二级详情固定在列表上方, 始终可见 -->
        <div v-if="expandedFac" class="fac-detail-box">
          <div class="fd-head">
            <b>{{ expandedFac.name }}</b>
            <button class="link-btn" @click.stop="onFocusFacility(expandedFac)">地图定位</button>
          </div>
          <div class="fd-addr">{{ expandedFac.address || '暂无地址' }}</div>
          <div class="fd-rows">
            <div v-for="(r, j) in detailRows(expandedFac)" :key="j" class="fd-row">
              <span class="fd-k">{{ r.k }}</span>
              <span class="fd-v">{{ r.v }}</span>
            </div>
          </div>
        </div>

        <!-- 设施列表独立滚动 -->
        <div class="fac-list-scroll">
          <div v-for="(f, i) in expandedFacilities" :key="i"
               :class="['fac-row', { open: expandedFac === f }]"
               @click="toggleFac(f)">
            <span class="fac-dot" :style="{ background: CAT_COLORS[expandedCat] || '#607d8b' }"></span>
            <div class="fac-main">
              <div class="fac-name">{{ f.name }}</div>
              <div class="fac-addr">{{ f.address || '暂无地址' }}</div>
            </div>
            <span class="fac-count" v-if="f.count > 1">×{{ f.count }}</span>
            <span class="caret">{{ expandedFac === f ? '▾' : '▸' }}</span>
          </div>
          <div v-if="!expandedFacilities.length" class="hint">该分类下无设施明细</div>
        </div>
      </div>
    </template>
    <div v-else class="empty">运行「生成生活圈」后可查看圈内设施统计<br /><span class="empty-sub">点击分类查看设施名称，再点击设施展开详情</span></div>
  </div>
</template>

<style scoped>
.stats-panel { display: flex; flex-direction: column; gap: 10px; }
.summary { display: flex; gap: 14px; flex-wrap: wrap; padding: 8px 10px; background: #f6f9fc; border-radius: 8px; }
.sum-item { color: var(--text-2); font-size: 12px; }
.sum-item b { color: var(--primary-dark); font-size: 16px; margin-right: 2px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 8px; }
.cat-card {
  display: flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px;
  background: #fff; cursor: pointer; transition: all .15s ease;
}
.cat-card:hover { border-color: var(--primary); }
.cat-card.open { border-color: var(--primary); background: var(--primary-light); }
.cat-card .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.cat-card .name { flex: 1; font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cat-card .cnt { font-weight: 700; font-size: 14px; }
.cat-card .caret { font-size: 10px; color: var(--text-3); }
.fac-detail { border: 1px solid var(--border); border-radius: 8px; padding: 8px; max-height: 380px; display: flex; flex-direction: column; }
.detail-title { font-size: 12px; color: var(--text-2); margin-bottom: 8px; }
.detail-hint { font-size: 11px; color: var(--text-3); margin-left: 6px; }
.fac-list-scroll { overflow-y: auto; margin-top: 8px; }
.fac-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px; border-radius: 6px; cursor: pointer;
  border-bottom: 1px dashed var(--border);
}
.fac-row:hover { background: #f6f9fc; }
.fac-row.open { background: var(--primary-light); }
.fac-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.fac-main { flex: 1; min-width: 0; }
.fac-name { font-size: 12.5px; color: var(--text); line-height: 1.4; }
.fac-addr { font-size: 11px; color: var(--text-3); line-height: 1.4; margin-top: 1px; }
.fac-count { font-size: 11px; color: var(--text-3); flex-shrink: 0; }
.fac-row .caret { font-size: 10px; color: var(--text-3); flex-shrink: 0; }
.fac-detail-box { border: 1px solid var(--primary); border-radius: 8px; padding: 8px 10px; margin-top: 8px; }
.fd-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 3px; }
.fd-head b { font-size: 12.5px; color: var(--text); }
.fd-addr { font-size: 11px; color: var(--text-3); margin-bottom: 6px; line-height: 1.5; }
.fd-rows { display: flex; flex-direction: column; gap: 3px; }
.fd-row { display: flex; font-size: 12px; }
.fd-k { width: 52px; color: var(--text-3); flex-shrink: 0; }
.fd-v { color: var(--text); }
.link-btn { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 12px; padding: 0; }
.link-btn:hover { text-decoration: underline; }
.empty { color: var(--text-3); text-align: center; padding: 24px 0; line-height: 1.8; }
.empty-sub { font-size: 11px; color: var(--text-3); }
</style>

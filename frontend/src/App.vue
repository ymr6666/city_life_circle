<script setup>
import { ref, watch } from 'vue'
import { store, togglePopLayer } from './store'
import { clearOverlays, clearRoads } from './mapLayers'
import MapView from './components/MapView.vue'
import AnalysisView from './views/AnalysisView.vue'
import ChoroplethView from './views/ChoroplethView.vue'
import PopulationView from './views/PopulationView.vue'

const tab = ref('analysis')
watch(tab, (v) => {
  store.activeTab = v
  // 切换视图时清空上一视图的地图覆盖层
  clearOverlays()
  clearRoads()
  // 进入人口分布页时自动开启人口图层
  if (v === 'population' && !store.popOn) togglePopLayer()
})
</script>

<template>
  <div class="app">
    <MapView />
    <AnalysisView v-show="tab === 'analysis'" />
    <ChoroplethView v-show="tab === 'choropleth'" />
    <PopulationView v-show="tab === 'population'" />

    <!-- 顶栏 -->
    <header class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="titles">
          <div class="name">城市时域生活圈分析系统</div>
          <div class="sub">City Life Circle Analysis</div>
        </div>
      </div>
      <nav class="tabs">
        <button :class="['tab', { active: tab === 'analysis' }]" @click="tab = 'analysis'">生活圈分析</button>
        <button :class="['tab', { active: tab === 'choropleth' }]" @click="tab = 'choropleth'">分级色彩</button>
        <button :class="['tab', { active: tab === 'population' }]" @click="tab = 'population'">人口分布</button>
      </nav>
      <div class="spacer"></div>
      <div class="server-badge">API · localhost:5000</div>
    </header>

    <!-- 全局 loading -->
    <transition name="fade">
      <div v-if="store.loading" class="loading-mask">
        <div class="spinner"></div>
        <div class="msg">{{ store.loadingMsg }}</div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.app { position: relative; width: 100%; height: 100%; }
.topbar {
  position: fixed; top: 0; left: 0; right: 0; height: 52px; z-index: 3000;
  background: #fff; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; padding: 0 16px; gap: 24px;
  box-shadow: var(--shadow-sm);
}
.brand { display: flex; align-items: center; gap: 10px; }
.logo {
  width: 30px; height: 30px; border-radius: 8px;
  background: linear-gradient(135deg, #1976d2, #4a9fe8);
  position: relative;
}
.logo::after {
  content: ''; position: absolute; inset: 7px;
  border: 2px solid #fff; border-radius: 50%;
  border-left-color: transparent; transform: rotate(30deg);
}
.titles .name { font-size: 15px; font-weight: 700; line-height: 1.1; }
.titles .sub { font-size: 10px; color: var(--text-3); letter-spacing: .06em; }
.tabs { display: flex; gap: 4px; }
.tab {
  border: none; background: none; padding: 7px 16px; font-size: 14px;
  color: var(--text-2); border-radius: 8px; cursor: pointer;
}
.tab:hover { background: var(--primary-light); color: var(--primary-dark); }
.tab.active { background: var(--primary); color: #fff; font-weight: 600; }
.spacer { flex: 1; }
.server-badge { font-size: 11px; color: var(--text-3); border: 1px solid var(--border); padding: 3px 8px; border-radius: 20px; }
.loading-mask {
  position: fixed; inset: 0; z-index: 5000;
  background: rgba(255,255,255,.72); backdrop-filter: blur(2px);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
}
.spinner {
  width: 38px; height: 38px; border-radius: 50%;
  border: 3px solid var(--primary-light); border-top-color: var(--primary);
  animation: spin .8s linear infinite;
}
.msg { color: var(--text-2); font-size: 14px; }
@keyframes spin { to { transform: rotate(360deg); } }
.fade-enter-active, .fade-leave-active { transition: opacity .2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>

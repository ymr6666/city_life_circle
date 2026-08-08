<script setup>
import { onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import { store, togglePopLayer } from '../store'

const el = ref(null)
const TIANDITU_KEY = '8b48e6297b3e826d59276c9bd56dbc7e'

function tianditu(layer) {
  // 天地图 WMTS 路径带 _w 后缀 (vec->vec_w, cva->cva_w, img->img_w, cia->cia_w)
  const path = layer + '_w'
  return L.tileLayer(
    `https://t{s}.tianditu.gov.cn/${path}/wmts?SERVICE=WMTS&REQUEST=GetTile` +
      `&VERSION=1.0.0&LAYER=${layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles` +
      `&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${TIANDITU_KEY}`,
    {
      subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
      maxZoom: 18,
      crossOrigin: 'anonymous',
      attribution: '&copy; 天地图',
    },
  )
}

onMounted(() => {
  // 用 SVG 渲染 (默认), 保证多边形/点位与底图瓦片缩放严格同步 (preferCanvas 会不同步)
  const map = L.map(el.value).setView([31.861, 117.285], 12)

  // 底图: 天地图矢量(+注记) / 天地图影像(+注记) / OSM
  const tiandituVec = L.layerGroup([tianditu('vec'), tianditu('cva')])
  const tiandituImg = L.layerGroup([tianditu('img'), tianditu('cia')])
  const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap',
  })
  tiandituVec.addTo(map)

  // 天地图瓦片连续失败时自动回退 OSM, 保证底图始终可见
  let tileErrCount = 0
  let fellBack = false
  tiandituVec.on('tileerror', () => {
    tileErrCount += 1
    if (!fellBack && tileErrCount >= 6) {
      fellBack = true
      map.removeLayer(tiandituVec)
      osm.addTo(map)
    }
  })

  // 人口密度底图图层 (预渲染瓦片, z9-14, 合肥范围外不显示)
  const popLayer = L.tileLayer('/tiles/pop/{z}/{x}/{y}.png', {
    minZoom: 9,
    maxNativeZoom: 14,
    maxZoom: 18,
    opacity: 0.85,
    bounds: [[31.55, 116.95], [32.20, 117.62]],
    attribution: '人口: WorldPop 2020',
  })

  L.control.layers({
    '天地图 矢量': tiandituVec,
    '天地图 影像': tiandituImg,
    'OSM 标准': osm,
  }, null, { position: 'bottomright' }).addTo(map)

  // 人口密度开关按钮 (常驻地图左下, 与人口页共用 togglePopLayer 保持状态一致)
  const popBtnEl = ref(null)
  const PopToggle = L.Control.extend({
    options: { position: 'bottomleft' },
    onAdd() {
      const btn = L.DomUtil.create('button', 'ctl-btn')
      btn.type = 'button'
      btn.title = '叠加 / 移除人口密度图层'
      btn.innerHTML = '<span class="ctl-dot"></span>人口密度'
      btn.onclick = (e) => {
        L.DomEvent.stopPropagation(e)
        togglePopLayer()
      }
      btn.addEventListener('dblclick', (e) => L.DomEvent.stopPropagation(e))
      popBtnEl.value = btn
      btn.classList.toggle('on', !!store.popOn)
      return btn
    },
  })
  map.addControl(new PopToggle())
  // store.popOn 变化时同步按钮高亮 (人口 Tab / 按钮任何来源)
  watch(() => store.popOn, (v) => {
    if (popBtnEl.value) popBtnEl.value.classList.toggle('on', !!v)
  })

  // 路网 pane 低于等时圈/设施层
  map.createPane('roads')
  map.getPane('roads').style.zIndex = 200

  // 缩放过程中隐藏覆盖层(缓冲区/点/标记), 完成后显示 —— 避免与底图动画错位
  const hidePanes = () => {
    map.getPane('overlayPane')?.classList.add('zoom-hide')
    map.getPane('markerPane')?.classList.add('zoom-hide')
  }
  const showPanes = () => {
    map.getPane('overlayPane')?.classList.remove('zoom-hide')
    map.getPane('markerPane')?.classList.remove('zoom-hide')
  }
  map.on('zoomstart', hidePanes)
  map.on('zoomend', showPanes)

  store.popLayer = popLayer
  store.map = map
})

function setView(lat, lng, zoom) {
  if (store.map) store.map.setView([lat, lng], zoom || 15)
}
defineExpose({ setView })
</script>

<template>
  <div ref="el" class="map-view"></div>
</template>

<style scoped>
.map-view {
  position: absolute;
  inset: 0;
  background: #e6eaef;
}
</style>

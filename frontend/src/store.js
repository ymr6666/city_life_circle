import { reactive } from 'vue'

export const store = reactive({
  map: null,
  activeTab: 'analysis',
  // 全局加载状态
  loading: false,
  loadingMsg: '',
  // 人口密度图层 (单一状态源)
  popLayer: null,
  popOn: false,
})

// 切换人口密度图层 (地图按钮 / 人口页共用, 保证状态一致)
export function togglePopLayer() {
  if (!store.map || !store.popLayer) return
  if (store.popOn) {
    store.map.removeLayer(store.popLayer)
    store.popOn = false
  } else {
    store.map.addLayer(store.popLayer)
    store.popOn = true
  }
}

export const CAT_COLORS = {
  hospital: '#d32f2f', supermarket: '#f57c00', park: '#388e3c', mall: '#7b1fa2',
  school_primary: '#1976d2', school_junior: '#303f9f', school_senior: '#283593',
  school_college: '#5e35b1', kindergarten: '#e91e63', market_food: '#6d4c41',
  street_commercial: '#fbc02d', street_pedestrian: '#00838f',
  pharmacy: '#ad1457', sports: '#2e7d32',
}

export const CAT_LABEL = {
  hospital: '医院', supermarket: '超市', park: '公园', mall: '商场',
  school_primary: '小学', school_junior: '初中', school_senior: '高中',
  school_college: '大学', kindergarten: '幼儿园', market_food: '农贸',
  street_commercial: '商业街', street_pedestrian: '步行街',
  pharmacy: '药店', sports: '体育',
}

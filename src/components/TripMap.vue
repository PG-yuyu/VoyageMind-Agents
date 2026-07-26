<template>
  <section class="trip-map panel">
    <header class="trip-map__head">
      <div>
        <p class="eyebrow">Map Resources</p>
        <h2>推荐地点地图</h2>
        <span>{{ validResources.length }} 个 Marker · {{ amapRoutes.length }} 条高德路线 · {{ invalidResources.length }} 个坐标提示</span>
      </div>
      <button class="ghost-button" :disabled="loading" @click="$emit('retry')">
        {{ loading ? '加载中' : '刷新地点' }}
      </button>
    </header>

    <p v-if="error" class="trip-map__notice">{{ error }}</p>
    <p v-if="mapModeNotice" class="trip-map__notice muted">{{ mapModeNotice }}</p>
    <p v-if="routeStatusNotice" class="trip-map__notice route">{{ routeStatusNotice }}</p>

    <div class="trip-map__layout">
      <section class="trip-map__stage">
        <div v-show="realMapReady" ref="realMapElement" class="real-map" :class="{ loading }"></div>
        <div v-if="!realMapReady" class="mock-map" :class="{ loading }">
          <RoutePolyline
            v-for="route in mockRouteLines"
            :key="route.key"
            :points="route.points"
          />
          <MapMarker
            v-for="marker in markerPositions"
            :key="marker.resource.place_id"
            :resource="marker.resource"
            :x="marker.x"
            :y="marker.y"
            :active="selectedPlaceId === marker.resource.place_id"
            @select="selectResource"
          />
          <MapInfoWindow
            v-if="selectedMarker"
            :resource="selectedMarker.resource"
            :x="selectedMarker.x"
            :y="selectedMarker.y"
          />
          <div v-if="!validResources.length" class="mock-map__empty">
            当前没有可渲染 Marker 的地点
          </div>
        </div>

        <footer class="trip-map__legend">
          <span class="attraction">景点</span>
          <span class="hotel">酒店</span>
          <span class="restaurant">餐厅</span>
          <span class="route">高德实际路线</span>
          <span class="warning">{{ realMapReady ? '真实高德地图 · 橙色描边为坐标待确认' : '轻量地图 · 只绘制高德已验证路线' }}</span>
        </footer>
      </section>

      <PlaceList
        :resources="resources"
        :selected-place-id="selectedPlaceId"
        @select="selectResource"
      />
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MapInfoWindow from './MapInfoWindow.vue'
import MapMarker from './MapMarker.vue'
import PlaceList from './PlaceList.vue'
import RoutePolyline from './RoutePolyline.vue'
import { createMapStore } from '../stores/mapStore'
import { loadAmapJsApi } from '../utils/amapLoader'

const props = defineProps({
  resources: {
    type: Array,
    default: () => []
  },
  loading: {
    type: Boolean,
    default: false
  },
  error: {
    type: String,
    default: ''
  },
  routes: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['select', 'retry'])
const mapStore = createMapStore(props.resources)
const realMapElement = ref(null)
const realMapReady = ref(false)
const realMapError = ref('')
const amapInstance = ref(null)
const amapInfoWindow = ref(null)
let amapApi = null
let amapMarkers = []
let amapPolylines = []

watch(
  () => props.resources,
  (resources) => mapStore.setResources(resources),
  { immediate: true, deep: true }
)

const resources = computed(() => mapStore.resources.value)
const validResources = computed(() => mapStore.validResources.value)
const invalidResources = computed(() => mapStore.invalidResources.value)
const selectedPlaceId = computed(() => mapStore.selectedPlaceId.value)

const coordinateBounds = computed(() => {
  const points = [
    ...validResources.value.map((resource) => [
      Number(resource.longitude),
      Number(resource.latitude)
    ]),
    ...amapRoutes.value.flatMap((route) => route.polyline)
  ].filter((point) => Number.isFinite(Number(point?.[0])) && Number.isFinite(Number(point?.[1])))
  if (!points.length) {
    return {
      minLongitude: 117.1,
      maxLongitude: 117.3,
      minLatitude: 39.0,
      maxLatitude: 39.2
    }
  }
  const longitudes = points.map((point) => Number(point[0]))
  const latitudes = points.map((point) => Number(point[1]))
  return {
    minLongitude: Math.min(...longitudes),
    maxLongitude: Math.max(...longitudes),
    minLatitude: Math.min(...latitudes),
    maxLatitude: Math.max(...latitudes)
  }
})

const markerPositions = computed(() => {
  return validResources.value.map((resource, index) => ({
    resource,
    index,
    ...positionForResource(resource, index)
  }))
})

const selectedMarker = computed(() => {
  return markerPositions.value.find((marker) => marker.resource.place_id === selectedPlaceId.value) || markerPositions.value[0] || null
})

const amapRoutes = computed(() => props.routes.filter(isVerifiedAmapRoute))
const nonAmapRoutes = computed(() => props.routes.filter((route) => !isVerifiedAmapRoute(route)))

const mockRouteLines = computed(() => {
  return amapRoutes.value
    .map((route, index) => ({
      key: `${route.origin_place_id}-${route.destination_place_id}-${index}`,
      points: route.polyline
        .map((point) => positionForCoordinate(point))
        .filter(Boolean)
    }))
    .filter((route) => route.points.length >= 2)
})

const mapModeNotice = computed(() => {
  if (realMapReady.value) return ''
  return realMapError.value ? `${realMapError.value}，当前使用轻量地图。` : ''
})

const routeStatusNotice = computed(() => {
  if (!props.routes.length) return ''
  if (amapRoutes.value.length) {
    const skippedText = nonAmapRoutes.value.length ? `，${nonAmapRoutes.value.length} 条未验证路线未绘制` : ''
    return `已渲染 ${amapRoutes.value.length} 条高德实际路线${skippedText}。`
  }
  return '当前路线未通过高德地图验证，不展示为真实路线。'
})

onMounted(() => {
  initializeRealMap()
})

onBeforeUnmount(() => {
  clearAmapPolylines()
  clearAmapMarkers()
  if (amapInstance.value) {
    amapInstance.value.destroy()
    amapInstance.value = null
  }
})

watch(
  validResources,
  () => {
    renderAmapMarkers()
    renderAmapRoutes()
  },
  { deep: true }
)

watch(
  amapRoutes,
  () => {
    renderAmapRoutes()
  },
  { deep: true }
)

watch(
  selectedPlaceId,
  (placeId) => {
    const resource = validResources.value.find((item) => item.place_id === placeId)
    if (resource) {
      focusAmapResource(resource)
    }
  }
)

function selectResource(resource) {
  mapStore.selectPlace(resource.place_id)
  focusAmapResource(resource)
  emit('select', resource)
}

async function initializeRealMap() {
  try {
    amapApi = await loadAmapJsApi()
    await nextTick()
    if (!realMapElement.value) return

    const first = validResources.value[0]
    amapInstance.value = new amapApi.Map(realMapElement.value, {
      center: first ? [Number(first.longitude), Number(first.latitude)] : [117.2, 39.12],
      resizeEnable: true,
      viewMode: '2D',
      zoom: first ? 13 : 11
    })
    amapInstance.value.addControl(new amapApi.Scale())
    amapInstance.value.addControl(new amapApi.ToolBar({ position: 'RB' }))
    amapInfoWindow.value = new amapApi.InfoWindow({
      offset: new amapApi.Pixel(0, -36)
    })
    realMapReady.value = true
    realMapError.value = ''
    renderAmapMarkers()
    renderAmapRoutes()
  } catch (error) {
    realMapReady.value = false
    realMapError.value = error.message || '真实地图加载失败'
  }
}

function renderAmapMarkers() {
  if (!realMapReady.value || !amapInstance.value || !amapApi) return

  clearAmapMarkers()
  amapMarkers = validResources.value.map((resource) => {
    const marker = new amapApi.Marker({
      position: [Number(resource.longitude), Number(resource.latitude)],
      title: resource.name,
      offset: new amapApi.Pixel(-18, -18),
      content: buildAmapMarkerContent(resource)
    })
    marker.on('click', () => {
      selectResource(resource)
      openAmapInfoWindow(resource, marker)
    })
    marker.setMap(amapInstance.value)
    return { placeId: resource.place_id, resource, marker }
  })

  if (amapMarkers.length) {
    setAmapFitView()
    const selected = validResources.value.find((resource) => resource.place_id === selectedPlaceId.value) || validResources.value[0]
    if (selected) focusAmapResource(selected)
  }
}

function renderAmapRoutes() {
  if (!realMapReady.value || !amapInstance.value || !amapApi) return

  clearAmapPolylines()
  amapPolylines = amapRoutes.value.map((route) => {
    const path = route.polyline.map((point) => [Number(point[0]), Number(point[1])])
    const polyline = new amapApi.Polyline({
      path,
      showDir: true,
      strokeColor: '#4f65ff',
      strokeOpacity: 0.86,
      strokeWeight: 7,
      strokeStyle: 'solid',
      lineJoin: 'round',
      lineCap: 'round',
      zIndex: 40
    })
    polyline.setMap(amapInstance.value)
    return polyline
  })
  setAmapFitView()
}

function clearAmapMarkers() {
  amapMarkers.forEach((item) => item.marker.setMap(null))
  amapMarkers = []
}

function clearAmapPolylines() {
  amapPolylines.forEach((polyline) => polyline.setMap(null))
  amapPolylines = []
}

function setAmapFitView() {
  if (!amapInstance.value) return
  const overlays = [
    ...amapMarkers.map((item) => item.marker),
    ...amapPolylines
  ]
  if (overlays.length) {
    amapInstance.value.setFitView(overlays, false, [80, 80, 80, 80])
  }
}

function focusAmapResource(resource) {
  if (!realMapReady.value || !amapInstance.value || !amapInfoWindow.value) return
  const markerItem = amapMarkers.find((item) => item.placeId === resource.place_id)
  if (!markerItem) return

  const position = markerItem.marker.getPosition()
  amapInstance.value.setCenter(position)
  openAmapInfoWindow(resource, markerItem.marker)
}

function openAmapInfoWindow(resource, marker) {
  if (!amapInfoWindow.value || !amapInstance.value) return
  amapInfoWindow.value.setContent(buildAmapInfoContent(resource))
  amapInfoWindow.value.open(amapInstance.value, marker.getPosition())
}

function buildAmapMarkerContent(resource) {
  const typeClass = resource.place_type || 'place'
  const initial = {
    attraction: '景',
    hotel: '住',
    restaurant: '食'
  }[resource.place_type] || '点'
  const unverifiedClass = resource.verified === false ? ' unverified' : ''
  return `<div class="amap-resource-marker ${typeClass}${unverifiedClass}"><span>${initial}</span><strong>${escapeHtml(resource.name)}</strong></div>`
}

function buildAmapInfoContent(resource) {
  const typeLabel = {
    attraction: '景点推荐',
    hotel: '住宿推荐',
    restaurant: '餐饮推荐'
  }[resource.place_type] || '推荐地点'
  const warning = resource.verified === false ? '<b>坐标未通过高德地图验证，请前端提示用户确认。</b>' : ''
  return `
    <article class="amap-info-card">
      <span>${typeLabel}</span>
      <strong>${escapeHtml(resource.name)}</strong>
      <p>${escapeHtml(resource.recommend_reason || resource.short_description || '')}</p>
      <small>${escapeHtml(resource.address || '')}</small>
      ${warning}
    </article>
  `
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function positionForResource(resource, index) {
  if (validResources.value.length === 1) {
    return { x: 50, y: 50 }
  }

  const position = positionForCoordinate([
    Number(resource.longitude),
    Number(resource.latitude)
  ])
  if (!position) return { x: 50, y: 50 }
  return {
    x: clamp(position.x + stagger(index), 12, 88),
    y: clamp(position.y - stagger(index), 14, 82)
  }
}

function positionForCoordinate(point) {
  const longitude = Number(point?.[0])
  const latitude = Number(point?.[1])
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return null

  const bounds = coordinateBounds.value
  const longitudeRange = bounds.maxLongitude - bounds.minLongitude || 0.01
  const latitudeRange = bounds.maxLatitude - bounds.minLatitude || 0.01
  const x = 14 + ((longitude - bounds.minLongitude) / longitudeRange) * 72
  const y = 78 - ((latitude - bounds.minLatitude) / latitudeRange) * 58

  return {
    x: clamp(x, 12, 88),
    y: clamp(y, 14, 82)
  }
}

function isVerifiedAmapRoute(route) {
  return (
    route?.source === 'amap' &&
    route?.verified === true &&
    Array.isArray(route.polyline) &&
    route.polyline.length >= 2
  )
}

function stagger(index) {
  return ((index % 3) - 1) * 2.5
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}
</script>

<style scoped>
.trip-map {
  display: grid;
  gap: 18px;
}

.trip-map__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.trip-map__head h2 {
  margin: 0;
  color: #101827;
  font-size: 24px;
}

.trip-map__head span {
  display: block;
  margin-top: 7px;
  color: #667386;
}

.trip-map__notice {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid #fed7aa;
  border-radius: 16px;
  background: #fff7ed;
  color: #b45309;
  font-weight: 800;
}

.trip-map__notice.muted {
  border-color: #d9e3ee;
  background: #f7faff;
  color: #647286;
}

.trip-map__notice.route {
  border-color: #c7d2fe;
  background: #eef3ff;
  color: #3043a4;
}

.trip-map__layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 22px;
}

.trip-map__stage {
  display: grid;
  align-content: start;
  gap: 12px;
  min-width: 0;
}

.real-map {
  min-height: 620px;
  overflow: hidden;
  border: 1px solid rgba(218, 228, 238, 0.9);
  border-radius: 24px;
}

.real-map.loading {
  opacity: 0.72;
}

.mock-map {
  position: relative;
  min-height: 620px;
  overflow: hidden;
  border: 1px solid rgba(218, 228, 238, 0.9);
  border-radius: 24px;
  background:
    linear-gradient(90deg, rgba(79, 101, 255, 0.09) 1px, transparent 1px),
    linear-gradient(rgba(79, 101, 255, 0.09) 1px, transparent 1px),
    radial-gradient(circle at 30% 24%, rgba(20, 184, 166, 0.13), transparent 28%),
    #eaf3f0;
  background-size: 44px 44px, 44px 44px, auto, auto;
}

.mock-map.loading::after {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.52);
  color: #172033;
  content: '正在加载地图资源';
  font-weight: 900;
}

.mock-map__empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #647286;
  font-weight: 900;
}

.trip-map__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trip-map__legend span {
  padding: 7px 10px;
  border-radius: 999px;
  background: #eef3ff;
  color: #3043a4;
  font-size: 12px;
  font-weight: 900;
}

.trip-map__legend .hotel {
  background: #e9fbf7;
  color: #0f766e;
}

.trip-map__legend .restaurant {
  background: #fff4df;
  color: #b45309;
}

.trip-map__legend .route {
  background: #edf2ff;
  color: #3f5cf6;
}

.trip-map__legend .warning {
  background: #fff8f1;
  color: #b45309;
}

:deep(.amap-resource-marker) {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 168px;
  min-height: 36px;
  padding: 6px 10px 6px 7px;
  border: 2px solid #fff;
  border-radius: 999px;
  background: #3f5cf6;
  color: #fff;
  box-shadow: 0 14px 28px rgba(31, 41, 55, 0.2);
}

:deep(.amap-resource-marker.hotel) {
  background: #0f766e;
}

:deep(.amap-resource-marker.restaurant) {
  background: #d97706;
}

:deep(.amap-resource-marker.unverified) {
  border-color: #f59e0b;
  box-shadow: 0 0 0 5px rgba(245, 158, 11, 0.18), 0 14px 28px rgba(31, 41, 55, 0.2);
}

:deep(.amap-resource-marker span) {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 12px;
  font-weight: 900;
}

:deep(.amap-resource-marker strong) {
  overflow: hidden;
  color: #fff;
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.amap-info-card) {
  display: grid;
  width: 260px;
  gap: 6px;
}

:deep(.amap-info-card span) {
  color: #4f65ff;
  font-size: 12px;
  font-weight: 900;
}

:deep(.amap-info-card strong) {
  color: #101827;
  font-size: 16px;
}

:deep(.amap-info-card p),
:deep(.amap-info-card small) {
  margin: 0;
  color: #647286;
  line-height: 1.55;
}

:deep(.amap-info-card b) {
  color: #b45309;
  font-size: 12px;
}

@media (max-width: 1180px) {
  .trip-map__layout {
    grid-template-columns: 1fr;
  }

  .real-map,
  .mock-map {
    min-height: 520px;
  }
}

@media (max-width: 760px) {
  .trip-map__head {
    flex-direction: column;
  }

  .real-map,
  .mock-map {
    min-height: 440px;
  }
}
</style>

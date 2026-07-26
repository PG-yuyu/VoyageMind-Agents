<template>
  <section class="trip-map">
    <header class="trip-map__head">
      <div>
        <p class="eyebrow">Route Map</p>
        <h2>推荐地点地图</h2>
        <span>地点、路线和坐标校验会集中展示在这里。</span>
      </div>
      <div class="trip-map__actions">
        <span class="status-pill">{{ realMapReady ? '高德地图已接入' : '轻量地图模式' }}</span>
        <button class="ghost-button" :disabled="loading" @click="$emit('retry')">
          {{ loading ? '加载中' : '刷新地点' }}
        </button>
      </div>
    </header>

    <div v-if="error || mapModeNotice" class="trip-map__alerts">
      <p v-if="error" class="trip-map__notice">{{ error }}</p>
      <p v-if="mapModeNotice" class="trip-map__notice muted">{{ mapModeNotice }}</p>
    </div>

    <div class="trip-map__layout">
      <section class="trip-map__stage">
        <div class="trip-map__canvas">
          <div ref="realMapElement" class="real-map" :class="{ ready: realMapReady, loading }"></div>
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
              v-if="hasManualSelection && selectedMarker"
              :resource="selectedMarker.resource"
              :x="selectedMarker.x"
              :y="selectedMarker.y"
            />
            <div v-if="!validResources.length" class="mock-map__empty">
              当前没有可渲染 Marker 的地点
            </div>
          </div>
        </div>

      </section>

      <aside class="trip-map__side">
        <section v-if="selectedResource" class="selected-place">
          <div>
            <span>{{ placeTypeLabel(selectedResource) }}</span>
            <strong>{{ selectedResource.name }}</strong>
            <p>{{ selectedResource.short_description || selectedResource.recommend_reason || '暂无地点摘要' }}</p>
          </div>
          <dl>
            <div>
              <dt>预算</dt>
              <dd>{{ selectedResource.price !== null && selectedResource.price !== undefined ? `约 ${selectedResource.price} 元` : '待定' }}</dd>
            </div>
            <div>
              <dt>时间</dt>
              <dd>{{ selectedResource.open_time || '全天' }}</dd>
            </div>
            <div>
              <dt>坐标</dt>
              <dd>{{ selectedResource.verified === false ? '待确认' : '已校验' }}</dd>
            </div>
          </dl>
        </section>

        <section class="map-summary">
          <article><span>地点</span><strong>{{ validResources.length }}</strong></article>
          <article><span>路线</span><strong>{{ amapRoutes.length }}</strong></article>
          <article><span>待确认</span><strong>{{ invalidResources.length }}</strong></article>
        </section>

        <PlaceList
          :resources="resources"
          :selected-place-id="selectedPlaceId"
          @select="selectResource"
        />
      </aside>
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
const hasManualSelection = ref(false)
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

const selectedResource = computed(() => {
  return resources.value.find((resource) => resource.place_id === selectedPlaceId.value) || resources.value[0] || null
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
    if (!hasManualSelection.value) return
    const resource = validResources.value.find((item) => item.place_id === placeId)
    if (resource) {
      focusAmapResource(resource)
    }
  }
)

function selectResource(resource) {
  hasManualSelection.value = true
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
    await nextTick()
    amapInstance.value.resize()
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

function placeTypeLabel(resource) {
  return {
    attraction: '景点',
    hotel: '酒店',
    restaurant: '餐饮'
  }[resource?.place_type] || '地点'
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}
</script>

<style scoped>
.trip-map {
  display: grid;
  gap: 14px;
  padding: 22px;
  border: 1px solid rgba(218, 228, 238, 0.9);
  border-radius: 26px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 26px 70px rgba(31, 41, 55, 0.08);
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
  line-height: 1.18;
}

.trip-map__head span {
  display: block;
  margin-top: 7px;
  color: #667386;
}

.trip-map__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}

.status-pill {
  min-height: 40px;
  padding: 10px 13px;
  border-radius: 999px;
  background: #e9fbf7;
  color: #0f8f7e;
  font-size: 13px;
  font-weight: 900;
}

.trip-map__alerts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trip-map__notice {
  margin: 0;
  min-height: 34px;
  padding: 8px 11px;
  border: 1px solid #fed7aa;
  border-radius: 999px;
  background: #fff7ed;
  color: #b45309;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
}

.trip-map__notice.muted {
  border-color: #d9e3ee;
  background: #f7faff;
  color: #647286;
}

.trip-map__layout {
  display: grid;
  grid-template-columns: minmax(620px, 1fr) 360px;
  align-items: stretch;
  gap: 16px;
  min-height: 0;
}

.trip-map__stage {
  display: grid;
  align-content: start;
  gap: 12px;
  min-width: 0;
}

.trip-map__canvas {
  position: relative;
  z-index: 0;
  height: clamp(500px, 58vh, 660px);
  min-height: 500px;
  overflow: hidden;
  border: 1px solid rgba(218, 228, 238, 0.9);
  border-radius: 20px;
  background: #f3f7fb;
  isolation: isolate;
  contain: layout paint;
}

.real-map,
.mock-map {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.real-map {
  z-index: 1;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s ease;
}

.real-map.ready {
  opacity: 1;
  pointer-events: auto;
}

.real-map.loading {
  opacity: 0.72;
}

.mock-map {
  z-index: 2;
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

:deep(.amap-container),
:deep(.amap-maps),
:deep(.amap-layers),
:deep(.amap-layer),
:deep(.amap-e) {
  max-width: 100%;
  max-height: 100%;
}

.trip-map__side {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  min-height: 0;
  height: clamp(500px, 58vh, 660px);
  overflow: hidden;
}

.selected-place {
  display: grid;
  gap: 14px;
  padding: 17px;
  border: 1px solid #dfe8f2;
  border-radius: 20px;
  background: #fbfdff;
}

.selected-place span {
  width: fit-content;
  padding: 5px 9px;
  border-radius: 999px;
  background: #e9fbf7;
  color: #0f8f7e;
  font-size: 12px;
  font-weight: 900;
}

.selected-place strong {
  display: block;
  margin-top: 9px;
  color: #101827;
  font-size: 20px;
  line-height: 1.25;
}

.selected-place p {
  display: -webkit-box;
  overflow: hidden;
  margin: 8px 0 0;
  color: #647286;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.selected-place dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.selected-place dl div {
  padding: 10px;
  border-radius: 14px;
  background: #f4f7fb;
}

.selected-place dt,
.selected-place dd {
  margin: 0;
}

.selected-place dt {
  color: #667386;
  font-size: 12px;
  font-weight: 850;
}

.selected-place dd {
  margin-top: 4px;
  color: #101827;
  font-size: 13px;
  font-weight: 900;
}

.map-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.map-summary article {
  display: grid;
  gap: 4px;
  min-height: 64px;
  padding: 11px;
  border: 1px solid #e1e9f2;
  border-radius: 16px;
  background: #f8fbff;
}

.map-summary span {
  color: #667386;
  font-size: 12px;
  font-weight: 850;
}

.map-summary strong {
  color: #101827;
  font-size: 22px;
  line-height: 1;
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
  width: 240px;
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

:deep(.amap-info-card p) {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

:deep(.amap-info-card b) {
  color: #b45309;
  font-size: 12px;
}

@media (max-width: 1180px) {
  .trip-map__layout {
    grid-template-columns: 1fr;
  }

  .trip-map__canvas {
    min-height: 520px;
  }

  .trip-map__side {
    height: auto;
    overflow: visible;
  }
}

@media (max-width: 760px) {
  .trip-map__head {
    flex-direction: column;
  }

  .trip-map {
    padding: 18px;
    border-radius: 22px;
  }

  .trip-map__canvas {
    height: 440px;
    min-height: 440px;
  }

  .map-summary {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <section class="trip-map">
    <header class="trip-map__head">
      <div>
        <p class="eyebrow">Route Map</p>
        <h2>推荐地点地图</h2>
        <span>地点、路线和坐标校验会集中展示在这里。</span>
      </div>
      <div class="trip-map__actions">
        <div class="map-mode-switch" role="tablist" aria-label="地图信息模式">
          <button :class="{ active: viewMode === 'info' }" @click="viewMode = 'info'">基本信息</button>
          <button :class="{ active: viewMode === 'guide' }" @click="openGuideMode()">AI 导游</button>
        </div>
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
              :clickable="viewMode === 'guide'"
              @select="selectRoute(route.source)"
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
              v-if="viewMode === 'info' && hasManualSelection && selectedMarker"
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

      <aside class="trip-map__side" :class="{ 'is-guide': viewMode === 'guide' }">
        <template v-if="viewMode === 'info'">
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

          <button class="map-refresh-button" :disabled="loading" @click="$emit('retry')">
            {{ loading ? '正在刷新地点' : '刷新地点数据' }}
          </button>
        </template>

        <section v-else class="guide-panel">
          <header class="guide-panel__head">
            <div>
              <span>AI Tour Guide</span>
              <strong>{{ guideTitle }}</strong>
            </div>
            <small>{{ guideTargetType }}</small>
          </header>

          <div class="guide-panel__messages">
            <article
              v-for="message in guideMessages"
              :key="message.id"
              class="guide-message"
              :class="message.role"
            >
              <span>{{ message.role === 'user' ? '你' : 'AI 导游' }}</span>
              <div v-if="message.audioUrl" class="guide-voice-playback">
                <p>{{ message.content || '已发送一条语音导游问题' }}</p>
                <audio :src="message.audioUrl" :type="message.audioType || 'audio/webm'" controls preload="metadata"></audio>
              </div>
              <p v-else-if="message.content">{{ message.content }}</p>
              <p v-else class="guide-thinking"><i></i><i></i><i></i></p>
            </article>
          </div>

          <div class="guide-panel__quick">
            <button
              v-for="question in guideQuickQuestions"
              :key="question"
              @click="guideInput = question"
            >
              {{ question }}
            </button>
          </div>

          <form class="guide-panel__input" @submit.prevent="sendGuideQuestion">
            <textarea
              v-model="guideInput"
              rows="3"
              placeholder="针对当前景点或路线提问，比如：这里适合拍照吗？附近有什么吃的？"
            ></textarea>
            <div class="guide-panel__actions">
              <button
                type="button"
                class="guide-voice-button"
                :class="{ recording: guideVoiceRecording }"
                :disabled="guideLoading && !guideVoiceRecording"
                @click="toggleGuideVoiceInput"
              >
                {{ guideVoiceRecording ? '停止' : '语音' }}
              </button>
              <button type="submit" :disabled="guideLoading">{{ guideLoading ? '回答中' : '提问' }}</button>
            </div>
          </form>
          <p v-if="guideVoiceRecording" class="guide-voice-status">正在录音，说完后点“停止”。</p>
          <p v-else-if="guideVoiceError" class="guide-voice-status error">{{ guideVoiceError }}</p>
        </section>
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
import { streamGuideChat, understandVoice } from '../api'
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
  },
  sessionId: {
    type: String,
    default: 'demo_session'
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
const viewMode = ref('info')
const guideTarget = ref(null)
const guideTargetKind = ref('place')
const guideInput = ref('')
const guideMessages = ref([])
const guideLoading = ref(false)
const guideVoiceRecording = ref(false)
const guideVoiceHint = ref('')
const guideVoiceError = ref('')
const guideVoiceObjectUrls = []
let guideMessageId = 0
let guideVoiceRecorder = null
let guideVoiceChunks = []
let guideVoiceRecognition = null
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
      source: route,
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

const guideTitle = computed(() => {
  if (!guideTarget.value) return '点击地图上的地点或路线'
  if (guideTargetKind.value === 'route') return routeTitle(guideTarget.value)
  return guideTarget.value.name
})

const guideTargetType = computed(() => {
  if (!guideTarget.value) return '等待选择'
  return guideTargetKind.value === 'route' ? '路线讲解' : placeTypeLabel(guideTarget.value)
})

const guideQuickQuestions = computed(() => {
  if (guideTargetKind.value === 'route') {
    return ['这段路怎么走更省力？', '沿途有什么值得停留？', '如果下雨怎么改？']
  }
  return ['这里最值得看什么？', '适合停留多久？', '附近有什么餐饮？']
})

onMounted(() => {
  initializeRealMap()
})

onBeforeUnmount(() => {
  stopGuideVoiceInput()
  guideVoiceObjectUrls.forEach((url) => URL.revokeObjectURL(url))
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

watch(viewMode, (mode) => {
  if (mode === 'guide') {
    amapInfoWindow.value?.close?.()
    if (!guideTarget.value && selectedResource.value) {
      setGuideTarget(selectedResource.value, 'place')
    }
  }
})

function openGuideMode() {
  viewMode.value = 'guide'
}

function selectResource(resource) {
  hasManualSelection.value = true
  mapStore.selectPlace(resource.place_id)
  focusAmapResource(resource)
  if (viewMode.value === 'guide') {
    setGuideTarget(resource, 'place')
  }
  emit('select', resource)
}

function selectRoute(route) {
  viewMode.value = 'guide'
  setGuideTarget(route, 'route')
}

function setGuideTarget(target, kind) {
  guideTarget.value = target
  guideTargetKind.value = kind
  guideInput.value = ''
  guideMessages.value = []
  requestGuideAnswer('请先用导游身份介绍这里。', true)
}

async function sendGuideQuestion() {
  const question = guideInput.value.trim()
  if (!question || guideLoading.value) return
  guideMessages.value.push({
    id: ++guideMessageId,
    role: 'user',
    content: question
  })
  guideInput.value = ''
  await requestGuideAnswer(question)
}

async function toggleGuideVoiceInput() {
  if (guideVoiceRecording.value) {
    stopGuideVoiceInput()
  } else {
    await startGuideVoiceInput()
  }
}

async function startGuideVoiceInput() {
  if (guideLoading.value || guideVoiceRecording.value) return
  if (!guideTarget.value) {
    guideVoiceError.value = '请先选择一个地点或路线。'
    return
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    guideVoiceError.value = '当前浏览器不支持录音，请继续使用文字输入。'
    return
  }

  try {
    guideVoiceError.value = ''
    guideVoiceHint.value = ''
    guideVoiceChunks = []
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = supportedGuideVoiceMimeType()
    guideVoiceRecorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream)

    guideVoiceRecorder.ondataavailable = (event) => {
      if (event.data?.size) guideVoiceChunks.push(event.data)
    }
    guideVoiceRecorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop())
      const audioBlob = new Blob(guideVoiceChunks, { type: guideVoiceRecorder?.mimeType || 'audio/webm' })
      guideVoiceRecorder = null
      guideVoiceChunks = []
      if (audioBlob.size) {
        submitGuideVoiceBlob(audioBlob)
      }
    }

    guideVoiceRecorder.start()
    guideVoiceRecording.value = true
  } catch (error) {
    guideVoiceRecording.value = false
    guideVoiceError.value = '无法启动麦克风，请检查浏览器权限。'
  }
}

function stopGuideVoiceInput() {
  if (guideVoiceRecorder && guideVoiceRecorder.state !== 'inactive') {
    guideVoiceRecorder.stop()
  }
  guideVoiceRecording.value = false
}

async function submitGuideVoiceBlob(audioBlob) {
  if (!guideTarget.value) return
  guideLoading.value = true
  const audioUrl = URL.createObjectURL(audioBlob)
  guideVoiceObjectUrls.push(audioUrl)
  try {
    const data = await understandVoice({
      sessionId: props.sessionId || 'demo_session',
      scene: 'guide',
      audioBlob,
      clientHint: ''
    })
    guideMessages.value.push({
      id: ++guideMessageId,
      role: 'user',
      content: data.display_text || '\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u5bfc\u6e38\u95ee\u9898',
      audioUrl,
      audioType: audioBlob.type || 'audio/webm'
    })

    if (!data.understood_text) {
      guideMessages.value.push({
        id: ++guideMessageId,
        role: 'assistant',
        content: data.asr_error ? `?????????????${data.asr_error}` : '\u8fd9\u6761\u8bed\u97f3\u6211\u6ca1\u6709\u542c\u6e05\uff0c\u8bf7\u518d\u5f55\u4e00\u6b21\uff0c\u6216\u8005\u76f4\u63a5\u6253\u5b57\u95ee\u6211\u3002'
      })
      guideLoading.value = false
      return
    }

    guideLoading.value = false
    await requestGuideAnswer(data.understood_text)
  } catch (error) {
    guideVoiceError.value = '\u8bed\u97f3\u53d1\u9001\u5931\u8d25\uff0c\u8bf7\u518d\u8bd5\u4e00\u6b21\u6216\u6539\u7528\u6587\u5b57\u8f93\u5165\u3002'
    guideLoading.value = false
  }
}

function startGuideHiddenSpeechRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!Recognition) return
  guideVoiceRecognition = new Recognition()
  guideVoiceRecognition.lang = 'zh-CN'
  guideVoiceRecognition.continuous = true
  guideVoiceRecognition.interimResults = true
  guideVoiceRecognition.onresult = (event) => {
    let text = ''
    for (let index = 0; index < event.results.length; index += 1) {
      text += event.results[index][0]?.transcript || ''
    }
    guideVoiceHint.value = text.trim()
  }
  guideVoiceRecognition.onerror = () => {}
  guideVoiceRecognition.start()
}

function stopGuideHiddenSpeechRecognition() {
  if (!guideVoiceRecognition) return
  try {
    guideVoiceRecognition.stop()
  } catch (error) {
    // The browser can already have stopped recognition.
  }
  guideVoiceRecognition = null
}

function supportedGuideVoiceMimeType() {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  return candidates.find((type) => window.MediaRecorder?.isTypeSupported?.(type)) || ''
}

async function requestGuideAnswer(message, intro = false) {
  if (!guideTarget.value) return
  guideLoading.value = true
  const assistantMessage = {
    id: ++guideMessageId,
    role: 'assistant',
    content: ''
  }
  guideMessages.value.push(assistantMessage)
  try {
    await streamGuideChat({
      session_id: props.sessionId || 'demo_session',
      target_type: guideTargetKind.value,
      target: guideTarget.value,
      message,
      intro,
      history: guideMessages.value
        .filter((item) => item.id !== assistantMessage.id)
        .map((item) => ({ role: item.role, content: item.content }))
    }, (_chunk, fullText) => {
      assistantMessage.content = fullText
    })
  } catch (error) {
    assistantMessage.content = guideTargetKind.value === 'route'
      ? buildRouteIntro(guideTarget.value)
      : buildPlaceIntro(guideTarget.value)
  } finally {
    guideLoading.value = false
  }
}

function buildPlaceIntro(resource) {
  const type = placeTypeLabel(resource)
  const reason = resource.recommend_reason || resource.short_description || '这个地点适合加入当前天津行程。'
  const address = resource.address ? `位置在${resource.address}。` : ''
  return `欢迎来到${resource.name}。它是本次路线中的${type}节点，${reason}${address}你可以继续问我它的看点、停留时间、附近餐饮或适合拍照的位置。`
}

function buildRouteIntro(route) {
  return `现在讲解${routeTitle(route)}。这段路径已经在地图上标出，适合用来判断两点之间的衔接、步行强度和是否需要换乘。你可以问我怎么走更轻松、沿途是否值得停留，或者下雨时怎么调整。`
}

function routeTitle(route) {
  const origin = resourceNameById(route?.origin_place_id) || '上一站'
  const destination = resourceNameById(route?.destination_place_id) || '下一站'
  return `${origin} → ${destination}`
}

function resourceNameById(placeId) {
  return resources.value.find((resource) => resource.place_id === placeId)?.name
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
      if (viewMode.value === 'info') {
        openAmapInfoWindow(resource, marker)
      }
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
    polyline.on('click', () => selectRoute(route))
    polyline.on('mouseover', () => polyline.setOptions({ strokeColor: '#14b8a6', strokeWeight: 8 }))
    polyline.on('mouseout', () => polyline.setOptions({ strokeColor: '#4f65ff', strokeWeight: 7 }))
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
  if (viewMode.value === 'info') {
    openAmapInfoWindow(resource, markerItem.marker)
  } else {
    amapInfoWindow.value.close()
  }
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
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.trip-map__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 0 4px;
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

.map-mode-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(92px, 1fr));
  gap: 4px;
  padding: 5px;
  border: 1px solid #dce7f2;
  border-radius: 999px;
  background: #f3f7fb;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.8);
}

.map-mode-switch button {
  min-height: 38px;
  padding: 0 16px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #647286;
  font-size: 13px;
  font-weight: 900;
  white-space: nowrap;
}

.map-mode-switch button.active {
  background: #172033;
  color: #fff;
  box-shadow: 0 12px 24px rgba(23, 32, 51, 0.18);
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
  grid-template-columns: minmax(760px, 1fr) 440px;
  align-items: stretch;
  gap: 18px;
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
  height: clamp(620px, 72vh, 820px);
  min-height: 620px;
  overflow: hidden;
  border: 1px solid rgba(218, 228, 238, 0.9);
  border-radius: 22px;
  background: #f3f7fb;
  box-shadow: 0 22px 58px rgba(31, 41, 55, 0.1);
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
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  gap: 12px;
  min-width: 0;
  min-height: 0;
  height: clamp(620px, 72vh, 820px);
  overflow: hidden;
}

.trip-map__side.is-guide {
  grid-template-rows: minmax(0, 1fr);
}

.selected-place {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid #dfe8f2;
  border-radius: 20px;
  background: #fbfdff;
  box-shadow: 0 18px 40px rgba(31, 41, 55, 0.07);
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
  margin-top: 8px;
  color: #101827;
  font-size: 19px;
  line-height: 1.25;
}

.selected-place p {
  display: -webkit-box;
  overflow: hidden;
  margin: 8px 0 0;
  color: #647286;
  font-size: 14px;
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
  padding: 9px 10px;
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
  min-height: 58px;
  padding: 10px 11px;
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

.map-refresh-button {
  min-height: 44px;
  border: 1px solid #dce7f2;
  border-radius: 16px;
  background: #fff;
  color: #172033;
  font-weight: 900;
}

.map-refresh-button:disabled {
  opacity: 0.65;
}

.guide-panel {
  align-self: stretch;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  gap: 12px;
  min-height: 0;
  height: 100%;
  padding: 16px;
  border: 1px solid #dfe8f2;
  border-radius: 22px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  box-shadow: 0 18px 44px rgba(31, 41, 55, 0.08);
}

.guide-panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e5edf5;
}

.guide-panel__head span {
  color: #4f65ff;
  font-size: 12px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.guide-panel__head strong {
  display: block;
  margin-top: 5px;
  color: #101827;
  font-size: 20px;
  line-height: 1.25;
}

.guide-panel__head small {
  flex: 0 0 auto;
  padding: 7px 10px;
  border-radius: 999px;
  background: #e9fbf7;
  color: #0f8f7e;
  font-size: 12px;
  font-weight: 900;
}

.guide-panel__messages {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.guide-message {
  display: grid;
  gap: 5px;
  max-width: 92%;
}

.guide-message span {
  color: #667386;
  font-size: 12px;
  font-weight: 900;
}

.guide-message p {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid #dfe8f2;
  border-radius: 16px;
  background: #fff;
  color: #253248;
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.guide-thinking {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  min-width: 66px;
  min-height: 42px;
}

.guide-thinking i {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #4f65ff;
  animation: guide-pulse 0.9s ease-in-out infinite;
}

.guide-thinking i:nth-child(2) {
  animation-delay: 0.12s;
}

.guide-thinking i:nth-child(3) {
  animation-delay: 0.24s;
}

@keyframes guide-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-3px);
  }
}

.guide-message.user {
  justify-self: end;
}

.guide-message.user span {
  text-align: right;
  color: #4f65ff;
}

.guide-message.user p {
  border-color: #b9c8ff;
  background: #eef3ff;
}

.guide-voice-playback {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid #b9c8ff;
  border-radius: 16px;
  background: #eef3ff;
}

.guide-voice-playback p {
  padding: 0;
  border: 0;
  background: transparent;
}

.guide-voice-playback audio {
  width: min(320px, 100%);
  height: 34px;
}

.guide-panel__quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.guide-panel__quick button {
  min-height: 32px;
  padding: 0 10px;
  border: 1px solid #dce7f2;
  border-radius: 999px;
  background: #fff;
  color: #44536a;
  font-size: 12px;
  font-weight: 900;
}

.guide-panel__input {
  display: grid;
  gap: 9px;
}

.guide-panel__input textarea {
  width: 100%;
  resize: none;
  min-height: 88px;
  padding: 12px;
  border: 1px solid #d6e2ee;
  border-radius: 16px;
  background: #fff;
  color: #172033;
  font: inherit;
  line-height: 1.5;
}

.guide-panel__input textarea:focus {
  outline: 3px solid rgba(79, 101, 255, 0.14);
  border-color: #8ea0ff;
}

.guide-panel__actions {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 10px;
}

.guide-panel__input button {
  min-height: 42px;
  border: 0;
  border-radius: 15px;
  background: linear-gradient(135deg, #4f65ff, #14b8a6);
  color: #fff;
  font-weight: 950;
}

.guide-panel__input button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.guide-panel__input .guide-voice-button {
  border: 1px solid #d9e3ee;
  background: #f8fbff;
  color: #4f65ff;
  box-shadow: none;
}

.guide-panel__input .guide-voice-button.recording {
  border-color: #ff6b7a;
  background: #fff1f3;
  color: #d9364f;
}

.guide-voice-status {
  margin: 8px 0 0;
  color: #4f65ff;
  font-size: 12px;
  font-weight: 850;
}

.guide-voice-status.error {
  color: #d9364f;
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

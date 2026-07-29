<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import TripMap from './components/TripMap.vue'
import {
  createSession,
  fetchKnowledgeDocuments,
  fetchMapResourcesByPlaceIds,
  getMockMapResources,
  healthCheck,
  loginAccount,
  registerAccount,
  streamPlanMessage,
  streamMessage,
  understandVoice,
  uploadKnowledgeDocument
} from './api'
import { modifyItinerary, previewItineraryAdjustment } from './api/adjustmentApi'
import BudgetPanel from './components/BudgetPanel.vue'
import TripTimeline from './components/TripTimeline.vue'
import AdjustmentPanel from './components/AdjustmentPanel.vue'

const localPictures = import.meta.glob('../pictures/**/*.{jpg,jpeg,png}', {
  eager: true,
  query: '?url',
  import: 'default'
})

const pages = [
  { id: 'plan', label: '智能规划' },
  { id: 'trip', label: '我的行程' },
  { id: 'history', label: '旅行历史' },
  { id: 'map', label: '路线地图' },
  { id: 'budget', label: '预算' },
  { id: 'qa', label: '旅行问答' },
  { id: 'library', label: '资料库' }
]

const activePage = ref('plan')
const prompt = ref('')
const planning = ref(false)
const voiceRecording = ref(false)
const voiceScene = ref('')
const voiceError = ref('')
const voiceHint = ref('')
const playingVoiceUrl = ref('')
let voiceRecorder = null
let voiceChunks = []
let voiceRecognition = null
const voiceObjectUrls = []
const sessionId = ref('')
const apiError = ref('')
const hasPlan = ref(false)
const STORAGE_KEY = 'voyage-mind-member1-state'

const messages = ref([])

function createSmoothTextStream(message, field = 'text') {
  let queue = ''
  let timer = null

  const pump = () => {
    if (!queue) {
      timer = null
      return
    }
    const step = Math.min(Math.max(Math.ceil(queue.length / 16), 1), 4)
    message[field] += queue.slice(0, step)
    queue = queue.slice(step)
    timer = window.setTimeout(pump, 18)
  }

  return {
    push(nextText) {
      if (!nextText) return
      queue += nextText
      if (!timer) pump()
    },
    async finish() {
      while (queue) {
        const step = Math.min(Math.max(Math.ceil(queue.length / 10), 1), 6)
        message[field] += queue.slice(0, step)
        queue = queue.slice(step)
        await new Promise((resolve) => window.setTimeout(resolve, 12))
      }
      message.isStreaming = false
    },
    fail(text) {
      queue = ''
      if (timer) window.clearTimeout(timer)
      timer = null
      message[field] = text
      message.isStreaming = false
    }
  }
}

function toggleVoicePlayback(event, url) {
  const audio = event.currentTarget.querySelector('audio')
  if (!audio) return
  if (playingVoiceUrl.value === url && !audio.paused) {
    audio.pause()
    playingVoiceUrl.value = ''
    return
  }
  document.querySelectorAll('audio[data-voice-player="true"]').forEach((item) => {
    if (item !== audio) item.pause()
  })
  audio.currentTime = 0
  audio.play()
  playingVoiceUrl.value = url
}

function stopVoicePlayback(url) {
  if (playingVoiceUrl.value === url) {
    playingVoiceUrl.value = ''
  }
}

const requirements = ref({
  city: '天津',
  days: null,
  people: null,
  total_budget: null,
  interests: [],
  must_visit: [],
  food_preferences: [],
  food_avoidances: [],
  transport_modes: ['walking', 'transit'],
  walking_limit_m: null,
  daily_start_time: '09:00',
  daily_end_time: '18:00',
  travel_pace: 'normal'
})

const planningProgress = ref([
  { title: '理解你的需求', desc: '识别目的地、天数、预算和兴趣偏好', status: 'pending' },
  { title: '筛选推荐地点', desc: '匹配景点、餐厅和住宿区域', status: 'pending' },
  { title: '安排每日路线', desc: '减少折返，插入午餐和晚餐时间', status: 'pending' },
  { title: '检查预算与强度', desc: '确认费用、步行距离和结束时间', status: 'pending' }
])

const progressStepTemplates = [
  {
    title: '理解你的需求',
    pending: '等待识别目的地、天数、预算和兴趣偏好',
    active: '正在拆解目的地、天数、预算和兴趣偏好',
    done: '已识别目的地、天数、预算和兴趣偏好'
  },
  {
    title: '筛选推荐地点',
    pending: '等待匹配景点、餐厅和住宿区域',
    active: '正在匹配景点、餐厅和住宿区域',
    done: '已完成地点候选筛选'
  },
  {
    title: '安排每日路线',
    pending: '等待安排每日动线和时间段',
    active: '正在减少折返，安排午餐和晚餐时间',
    done: '已生成每日路线草案'
  },
  {
    title: '检查预算与强度',
    pending: '等待校验费用、步行距离和结束时间',
    active: '正在校验预算、步行强度和开放时间',
    done: '已完成预算与强度检查'
  }
]

const itineraryDays = ref([
  {
    day: 1,
    title: '五大道与海河夜景',
    date: '演示日期',
    walking: '6.5 公里',
    cost: 760,
    hotel: '和平路附近酒店',
    routeTime: '78 分钟',
    area: '和平 · 海河',
    highlights: ['上午慢逛五大道', '下午衔接城市地标', '晚上安排海河夜景'],
    items: [
      { time: '08:40', title: '酒店出发', tag: '出发准备', desc: '早餐后出发，准备好身份证、充电宝和轻便外套。', cost: 0, route: '和平路出发 · 地铁/打车约 15 分钟' },
      { time: '09:10', title: '五大道文化旅游区', tag: '近代建筑', desc: '从民园广场进入，重点看英式、法式和意式风格建筑。', cost: 0, route: '步行游览 · 预留 2 小时' },
      { time: '11:20', title: '民园广场休息拍照', tag: '城市漫游', desc: '安排短休息，适合拍照和补水，避免上午步行过满。', cost: 30, route: '区内步行约 8 分钟' },
      { time: '12:20', title: '桂园餐厅天津菜午餐', tag: '餐饮', desc: '选择罾蹦鲤鱼、八珍豆腐等天津风味，人均预算可控。', cost: 220, route: '步行/打车约 12 分钟' },
      { time: '14:00', title: '瓷房子外观', tag: '城市地标', desc: '安排外观打卡和周边街区，不强制购票入内。', cost: 50, route: '打车约 10 分钟' },
      { time: '15:20', title: '张学良故居', tag: '名人故居', desc: '补充近代历史内容，游览强度比继续逛街更低。', cost: 90, route: '步行约 9 分钟' },
      { time: '17:00', title: '意式风情区', tag: '街区文化', desc: '傍晚逛街区、咖啡馆和建筑外观，衔接晚餐。', cost: 120, route: '地铁/打车约 18 分钟' },
      { time: '19:00', title: '海河夜景与天津之眼外观', tag: '夜景', desc: '沿海河看夜景，可根据体力选择是否乘船或乘坐摩天轮。', cost: 250, route: '步行 + 打车约 25 分钟' }
    ]
  },
  {
    day: 2,
    title: '古文化街与滨海风光',
    date: '演示日期',
    walking: '5.8 公里',
    cost: 690,
    hotel: '和平路附近酒店',
    routeTime: '88 分钟',
    area: '南开 · 滨海',
    highlights: ['上午逛传统街区', '午后加入室内展馆', '傍晚看滨海风光'],
    items: [
      { time: '08:50', title: '酒店退房/寄存行李', tag: '出发准备', desc: '先处理行李，方便第二天轻装游览。', cost: 0, route: '酒店前台办理约 10 分钟' },
      { time: '09:20', title: '古文化街', tag: '传统街区', desc: '看泥人张、杨柳青年画等非遗与老字号。', cost: 60, route: '地铁/打车约 18 分钟' },
      { time: '10:50', title: '天后宫', tag: '民俗文化', desc: '了解天津港口与妈祖文化，游览时间不宜过长。', cost: 20, route: '古文化街内步行约 6 分钟' },
      { time: '12:10', title: '南市食品街午餐', tag: '餐饮', desc: '尝试锅巴菜、煎饼果子、熟梨糕等天津小吃。', cost: 180, route: '打车约 12 分钟' },
      { time: '13:50', title: '天津博物馆', tag: '博物馆', desc: '安排室内展馆，适合避暑或雨天替代。', cost: 0, route: '地铁约 25 分钟' },
      { time: '15:40', title: '滨海新区图书馆', tag: '建筑打卡', desc: '如果时间充裕，安排网红建筑打卡；时间紧可替换为市区咖啡休息。', cost: 40, route: '城际/地铁换乘约 45 分钟' },
      { time: '17:20', title: '东疆湾或滨海广场', tag: '海边风光', desc: '看滨海风光，控制停留时间避免返程太晚。', cost: 80, route: '打车约 20 分钟' },
      { time: '19:00', title: '返回市区取行李', tag: '返程', desc: '预留回天津站或酒店取行李的时间。', cost: 310, route: '城际/地铁约 50 分钟' }
    ]
  }
])

const defaultItineraryTemplates = itineraryDays.value.map((day) => ({
  ...day,
  items: day.items.map((item) => ({ ...item })),
  highlights: [...day.highlights]
}))

const activeDay = ref(1)
const smartAdjustInput = ref('')
const smartAdjustPreview = ref(null)
const pendingAdjustedItinerary = ref(null)
const appliedAdjustment = ref('')
const applyingAdjustment = ref(false)
const selectedPlace = ref(null)
const recommendationResult = ref(null)
const currentItineraryPayload = ref(null)
const recommendedRoutes = ref([])

// 智能修改状态：连接后端
const currentItineraryId = ref('')
const baseVersion = ref(1)
const savedItinerary = ref(false) // 是否已保存到后端

// ── 评价系统状态 ─────────────────────────────────
const showDiff = ref(false)              // 是否显示版本对比
const tripDiffData = ref(null)           // TripDiff | null
const showTimeline = ref(false)          // 切换时间轴视图
const showAdjustments = ref(false)       // 切换调整说明视图

const mapResources = ref(getMockMapResources())
const mapLoading = ref(false)
const mapError = ref('')
const routeStops = computed(() => {
  const items = activeItinerary.value?.items || []
  const stops = [items[1], items[3], items[5], items[items.length - 1]].filter(Boolean)
  return stops.map((item) => item.title.replace('午门入园', '').replace('午餐', ''))
})

const placeDetails = {
  五大道文化旅游区: {
    image: getPlaceImage({ place_id: 'tj_place_005', item_type: 'attraction', title: '五大道文化旅游区' }),
    title: '五大道文化旅游区',
    desc: '天津近代建筑最集中的街区之一，适合慢行、拍照和了解租界时期建筑风格。',
    tips: ['建议上午游览', '民园广场可作为起点', '步行时间建议控制在 2 小时左右']
  },
  民园广场休息拍照: {
    image: getPlaceImage({ place_id: 'tj_place_006', item_type: 'attraction', title: '民园广场' }),
    title: '民园广场',
    desc: '五大道核心休息点，适合拍照、补水和调整游览节奏。',
    tips: ['适合短暂停留', '周边咖啡店较多', '可衔接五大道建筑群']
  },
  瓷房子外观: {
    image: getPlaceImage({ place_id: 'tj_place_007', item_type: 'attraction', title: '瓷房子' }),
    title: '瓷房子',
    desc: '天津市区标志性建筑之一，外观辨识度高，可根据预算选择是否入内。',
    tips: ['可只看外观', '雨天可缩短停留', '周边适合街区漫游']
  },
  张学良故居: {
    image: getPlaceImage({ place_id: 'tj_place_008', item_type: 'attraction', title: '张学良故居' }),
    title: '张学良故居',
    desc: '近代历史相关景点，适合补充人物故事和天津城市历史内容。',
    tips: ['室内外结合', '适合低强度游览', '建议预留 40-60 分钟']
  },
  意式风情区: {
    image: getPlaceImage({ place_id: 'tj_place_009', item_type: 'attraction', title: '意式风情区' }),
    title: '意式风情区',
    desc: '以欧式建筑、餐饮和街区氛围为主，适合傍晚散步和晚餐。',
    tips: ['傍晚体验更好', '餐厅选择多', '雨天可缩短露天停留']
  },
  海河夜景与天津之眼外观: {
    image: getPlaceImage({ place_id: 'tj_place_010', item_type: 'attraction', title: '海河夜景与天津之眼' }),
    title: '海河夜景与天津之眼',
    desc: '天津夜游核心体验，可选择步行、车览、游船或摩天轮外观打卡。',
    tips: ['晚间灯光更好', '雨天建议车览', '注意返程交通时间']
  },
  天津博物馆: {
    image: getPlaceImage({ place_id: 'tj_place_001', item_type: 'attraction', title: '天津博物馆' }),
    title: '天津博物馆',
    desc: '室内文化展馆，适合雨天、高温或需要降低步行强度时替代。',
    tips: ['适合雨天', '通常无需高额门票', '可作为下午替代方案']
  }
}

const budget = ref([
  { label: '酒店', value: 720, color: '#5b6cff' },
  { label: '门票', value: 170, color: '#14b8a6' },
  { label: '餐饮', value: 620, color: '#f59e0b' },
  { label: '交通', value: 230, color: '#ef6f88' }
])

const sources = [
  {
    title: '五大道游览资料.pdf',
    desc: '五大道适合安排上午慢行，民园广场可作为路线起点。',
    meta: '来源证据 · 第 2 页'
  },
  {
    title: '天津博物馆资料.md',
    desc: '天津博物馆适合雨天或高温时段，可作为室内替代方案。',
    meta: '来源证据 · 段落 14'
  },
  {
    title: '天津餐饮文化.txt',
    desc: '南市食品街、五大道周边适合衔接天津菜和本地小吃。',
    meta: '来源证据 · 段落 8'
  }
]

const qaSuggestions = [
  '五大道适合安排上午还是下午？',
  '天津哪些景点适合雨天？',
  '海河夜景怎么安排不累？',
  '带父母游天津怎么减少步行？'
]

const KNOWLEDGE_BASE_ID = 'kb_demo'
const documents = ref([])
const uploadInput = ref(null)
const uploadHint = ref('连接 LangChain_RAG 知识库，上传后会写入 Chroma')
const libraryLoading = ref(false)
const uploadingDocuments = ref(false)
const authMode = ref('login')
const authOpen = ref(false)
const isAuthenticated = ref(false)
const authError = ref('')
const currentUser = ref(null)
const authForm = ref({
  username: '',
  password: '',
  nickname: ''
})

const tripHistory = ref([
])

const extraDayTemplates = [
  {
    title: '天津博物馆与梅江休闲',
    walking: '4.8 公里',
    cost: 520,
    hotel: '和平路附近酒店',
    routeTime: '62 分钟',
    area: '河西 · 梅江',
    highlights: ['上午安排室内展馆', '下午降低步行强度', '晚上选择轻松餐饮'],
    items: [
      { time: '09:00', title: '酒店出发', tag: '出发准备', desc: '根据前两天体力调整出发时间，避免连续早起。', cost: 0, route: '地铁/打车约 20 分钟' },
      { time: '09:40', title: '天津博物馆', tag: '博物馆', desc: '安排室内展馆，适合补充城市历史和降低户外步行。', cost: 0, route: '预留 2 小时' },
      { time: '12:00', title: '河西商圈午餐', tag: '餐饮', desc: '选择商场内餐厅，方便休息和补给。', cost: 180, route: '步行/打车约 10 分钟' },
      { time: '14:00', title: '梅江公园轻松散步', tag: '城市休闲', desc: '安排低强度户外活动，适合作为第三天缓冲。', cost: 20, route: '打车约 18 分钟' },
      { time: '16:00', title: '咖啡休息与整理照片', tag: '休整', desc: '预留弹性时间，方便根据天气或体力继续调整。', cost: 90, route: '周边步行约 8 分钟' },
      { time: '18:00', title: '天津菜晚餐', tag: '餐饮', desc: '补充本地菜体验，预算保持可控。', cost: 230, route: '打车约 15 分钟' }
    ]
  },
  {
    title: '滨海新区建筑与海边',
    walking: '5.2 公里',
    cost: 640,
    hotel: '和平路附近酒店',
    routeTime: '110 分钟',
    area: '滨海新区',
    highlights: ['全天安排滨海方向', '减少市区和滨海之间折返', '预留返程交通时间'],
    items: [
      { time: '08:50', title: '前往滨海新区', tag: '跨区交通', desc: '提前出发，把滨海方向集中安排在同一天。', cost: 80, route: '城际/地铁约 50 分钟' },
      { time: '10:10', title: '滨海新区图书馆', tag: '建筑打卡', desc: '参观网红建筑空间，适合拍照和短暂停留。', cost: 0, route: '预留 1.5 小时' },
      { time: '12:00', title: '滨海商圈午餐', tag: '餐饮', desc: '就近用餐，避免中午折返市区。', cost: 180, route: '步行/打车约 12 分钟' },
      { time: '14:00', title: '国家海洋博物馆', tag: '展馆', desc: '安排大型室内展馆，适合亲子、雨天或高温天气。', cost: 80, route: '打车约 25 分钟' },
      { time: '16:40', title: '东疆湾海边', tag: '海边风光', desc: '傍晚看海边风光，根据天气决定停留时长。', cost: 80, route: '打车约 20 分钟' },
      { time: '18:30', title: '返回市区', tag: '返程', desc: '预留晚高峰和跨区交通时间。', cost: 220, route: '城际/地铁约 60 分钟' }
    ]
  },
  {
    title: '大学城与西青慢游',
    walking: '5.0 公里',
    cost: 480,
    hotel: '和平路附近酒店',
    routeTime: '86 分钟',
    area: '南开 · 西青',
    highlights: ['节奏更慢', '适合补充城市生活感', '保留下午弹性'],
    items: [
      { time: '09:20', title: '酒店出发', tag: '出发准备', desc: '第五天以轻松收尾为主，不安排过密行程。', cost: 0, route: '地铁/打车约 20 分钟' },
      { time: '10:00', title: '南开大学周边', tag: '校园周边', desc: '感受天津校园和周边街区氛围，控制步行强度。', cost: 0, route: '步行游览约 1 小时' },
      { time: '11:30', title: '水上公园', tag: '城市公园', desc: '安排开阔公园休闲，适合拍照和放慢节奏。', cost: 0, route: '打车约 12 分钟' },
      { time: '13:00', title: '奥城午餐', tag: '餐饮', desc: '选择餐饮集中区域，方便不同口味同行人。', cost: 190, route: '打车约 10 分钟' },
      { time: '15:00', title: '杨柳青古镇', tag: '传统文化', desc: '如果体力允许，补充年画和古镇文化体验。', cost: 70, route: '打车约 35 分钟' },
      { time: '18:00', title: '返程准备', tag: '返程', desc: '预留取行李和前往车站时间。', cost: 220, route: '打车/地铁约 45 分钟' }
    ]
  }
]

const activeItinerary = computed(() => itineraryDays.value.find((day) => day.day === activeDay.value) || itineraryDays.value[0])
const fallbackMapPlaceIds = ['tj_hotel_002', 'tj_place_003', 'tj_restaurant_002']
const amapRouteCount = computed(() => recommendedRoutes.value.filter(isVerifiedAmapRoute).length)
const itinerarySourceText = computed(() => currentItineraryPayload.value
  ? '当前行程来自后端智能体生成结果，后续可继续对话修改。'
  : '当前为本地演示方案，接口返回完整行程后会自动替换。'
)
const mapPlaceIds = computed(() => {
  const itineraryIds = itineraryDays.value
    .flatMap((day) => Array.isArray(day.items) ? day.items : [])
    .map((item) => item?.place_id)
    .filter(Boolean)
  const ids = [
    ...itineraryIds,
    ...recommendationPlaces(recommendationResult.value)
    .map((place) => place.place_id)
    .filter(Boolean)
  ]
  return ids.length ? Array.from(new Set(ids)) : fallbackMapPlaceIds
})
const totalSpent = computed(() => budget.value.reduce((sum, item) => sum + item.value, 0))
const remainingBudget = computed(() => (requirements.value.total_budget || 0) - totalSpent.value)
const budgetPercent = computed(() => Math.min(100, Math.round((totalSpent.value / (requirements.value.total_budget || totalSpent.value)) * 100)))

const preferenceSummary = computed(() => [
  { label: '目的地', value: requirements.value.city || '待补充' },
  { label: '天数', value: requirements.value.days ? `${requirements.value.days} 天` : '待补充' },
  { label: '人数', value: `${requirements.value.people || 1} 人` },
  { label: '预算', value: requirements.value.total_budget ? `${requirements.value.total_budget} 元` : '不限预算' },
  { label: '兴趣', value: requirements.value.interests?.join(' / ') || '待补充' },
  { label: '步行上限', value: `${Math.round((requirements.value.walking_limit_m || 8000) / 1000)} 公里/天` }
])

onMounted(async () => {
  restorePersistedState()
  syncBudgetFromItineraryDays()
  loadMapResources()
  void loadKnowledgeDocuments()
  try {
    await healthCheck()
    if (!sessionId.value) {
      const session = await createSession(currentUser.value?.user_id || 'demo_user')
      sessionId.value = session.session_id
    }
  } catch (error) {
    apiError.value = error.message
    if (!sessionId.value) {
      sessionId.value = `local_${Date.now()}`
    }
  }
})

onBeforeUnmount(() => {
  voiceObjectUrls.forEach((url) => URL.revokeObjectURL(url))
})

watch(
  [
    activePage, sessionId, hasPlan, messages, requirements,
    itineraryDays, activeDay, tripHistory,
    currentUser, isAuthenticated, recommendationResult,
    recommendedRoutes, mapResources, budget,
    currentItineraryId, baseVersion, documents, uploadHint,
  ],
  persistState,
  { deep: true }
)

watch(
  messages,
  () => {
    const filtered = messages.value.filter((message) => !isWorkflowChatMessage(message))
    if (filtered.length !== messages.value.length) {
      messages.value = filtered
    }
  },
  { deep: true }
)

function persistState() {
  if (typeof window === 'undefined') return
  const payload = {
    activePage: activePage.value,
    sessionId: sessionId.value,
    hasPlan: hasPlan.value,
    messages: messages.value,
    requirements: requirements.value,
    itineraryDays: itineraryDays.value,
    activeDay: activeDay.value,
    tripHistory: tripHistory.value,
    currentUser: currentUser.value,
    isAuthenticated: isAuthenticated.value,
    recommendationResult: recommendationResult.value,
    currentItineraryPayload: currentItineraryPayload.value,
    recommendedRoutes: recommendedRoutes.value,
    mapResources: mapResources.value,
    documents: documents.value,
    uploadHint: uploadHint.value,
    budget: budget.value,
    currentItineraryId: currentItineraryId.value,
    baseVersion: baseVersion.value,
  }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch (error) {
    apiError.value = '本地历史保存空间不足，部分记录可能无法持久化。'
  }
}

function restorePersistedState() {
  if (typeof window === 'undefined') return
  let payload = null
  try {
    payload = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null')
  } catch (_error) {
    window.localStorage.removeItem(STORAGE_KEY)
    return
  }
  if (!payload || typeof payload !== 'object') return

  activePage.value = payload.activePage || 'plan'
  sessionId.value = payload.sessionId || ''
  hasPlan.value = Boolean(payload.hasPlan)
  messages.value = Array.isArray(payload.messages)
    ? payload.messages.filter((message) => !isWorkflowChatMessage(message))
    : []
  requirements.value = payload.requirements && typeof payload.requirements === 'object'
    ? { ...requirements.value, ...payload.requirements }
    : requirements.value
  itineraryDays.value = Array.isArray(payload.itineraryDays) && payload.itineraryDays.length
    ? payload.itineraryDays
    : itineraryDays.value
  activeDay.value = Number(payload.activeDay) || 1
  tripHistory.value = Array.isArray(payload.tripHistory) ? payload.tripHistory : []
  currentUser.value = payload.currentUser || null
  isAuthenticated.value = Boolean(payload.isAuthenticated && payload.currentUser)
  recommendationResult.value = payload.recommendationResult || null
  currentItineraryPayload.value = payload.currentItineraryPayload || null
  recommendedRoutes.value = Array.isArray(payload.recommendedRoutes) ? payload.recommendedRoutes : []
  mapResources.value = Array.isArray(payload.mapResources) && payload.mapResources.length
    ? payload.mapResources
    : mapResources.value
  documents.value = Array.isArray(payload.documents) ? payload.documents : documents.value
  uploadHint.value = payload.uploadHint || uploadHint.value
  budget.value = Array.isArray(payload.budget) && payload.budget.length ? payload.budget : budget.value
  currentItineraryId.value = payload.currentItineraryId || ''
  baseVersion.value = payload.baseVersion || 1
}

function isWorkflowChatMessage(message) {
  if (!message || message.role !== 'assistant') return false
  const text = String(message.text || message.content || '')
  return (
    text.includes('已生成天津')
    || text.includes('自由行方案')
    || text.includes('已根据你的要求调整行程')
    || text.includes('已根据你的要求更新行程')
    || text.includes('已调整第')
    || text.includes('调整类型')
    || text.includes('本地模拟调整')
  )
}

async function loadMapResources() {
  mapLoading.value = true
  try {
    const payload = await fetchMapResourcesByPlaceIds(mapPlaceIds.value)
    mapResources.value = payload.resources?.length
      ? mergeMapResourceDetails(payload.resources, recommendationResult.value)
      : fallbackRecommendationResources()
    mapError.value = payload.warnings?.length ? payload.warnings.join('；') : ''
  } catch (error) {
    mapResources.value = fallbackRecommendationResources()
    mapError.value = recommendationResult.value
      ? '地图资源接口暂不可用，当前使用推荐结果中的坐标展示。'
      : '地图接口暂不可用，当前显示本地演示推荐地点。'
  } finally {
    mapLoading.value = false
  }
}

async function sendPrompt(targetPage = 'trip') {
  const text = prompt.value.trim()
  if (!text || planning.value) return
  prompt.value = ''
  await submitPromptText(text, targetPage)
}

function setPlanningProgress(activeIndex) {
  planningProgress.value = progressStepTemplates.map((item, index) => {
    const status = index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending'
    return {
      title: item.title,
      desc: item[status],
      status
    }
  })
}

function startPlanningProgressFlow(targetPage) {
  setPlanningProgress(0)
}

function applyPlanningProgressEvent(event) {
  if (event?.type !== 'progress') return
  const index = Number(event.index)
  if (!Number.isInteger(index) || index < 0 || index >= planningProgress.value.length) return

  planningProgress.value = planningProgress.value.map((item, itemIndex) => {
    if (itemIndex < index && item.status !== 'failed') {
      return {
        ...item,
        desc: item.status === 'done' ? item.desc : progressStepTemplates[itemIndex].done,
        status: 'done'
      }
    }
    if (itemIndex === index) {
      return {
        ...item,
        desc: event.desc || progressStepTemplates[itemIndex][event.status] || item.desc,
        status: event.status || item.status
      }
    }
    return item
  })
}

function updatePlanningProgressFromResult(response, mode = 'api') {
  const backendItinerary = response?.itinerary || response?.data?.itinerary
  const demoItineraryDone = mode === 'demo' && hasPlan.value && itineraryDays.value.length > 0
  const currentProgress = planningProgress.value
  const requirementsDone = Boolean(response?.requirements || demoItineraryDone || currentProgress[0]?.status === 'done')
  const recommendationDone = Boolean(response?.recommendation_result || recommendationResult.value || demoItineraryDone || currentProgress[1]?.status === 'done')
  const itineraryDone = Boolean(backendItinerary?.days?.length || demoItineraryDone || currentProgress[2]?.status === 'done')
  const evaluationDone = Boolean(response?.evaluation || demoItineraryDone || currentProgress[3]?.status === 'done')

  planningProgress.value = [
    {
      title: progressStepTemplates[0].title,
      desc: requirementsDone
        ? (demoItineraryDone ? '已使用演示解析结果补全基础需求' : progressStepTemplates[0].done)
        : '等待后端返回完整需求字段',
      status: requirementsDone ? 'done' : 'pending'
    },
    {
      title: progressStepTemplates[1].title,
      desc: recommendationDone
        ? (demoItineraryDone ? '已按演示规则生成地点候选' : '已收到推荐模块返回的地点候选')
        : '等待成员二推荐模块返回地点、餐厅和住宿',
      status: recommendationDone ? 'done' : 'pending'
    },
    {
      title: progressStepTemplates[2].title,
      desc: itineraryDone
        ? (demoItineraryDone ? '已生成前端演示行程，后续可替换为真实规划接口' : routeProgressText())
        : '等待成员三生成完整每日行程',
      status: itineraryDone ? 'done' : 'pending'
    },
    {
      title: progressStepTemplates[3].title,
      desc: evaluationDone
        ? (currentProgress[3]?.status === 'done' ? currentProgress[3].desc : (demoItineraryDone ? '已完成演示预算与步行强度估算' : progressStepTemplates[3].done))
        : '等待预算、步行强度和开放时间校验结果',
      status: evaluationDone ? 'done' : 'pending'
    }
  ]
}

async function submitPromptText(text, targetPage = 'trip', displayText = text, audioUrl = '', audioType = '') {
  if (!text || planning.value) return

  messages.value.push({ role: 'user', text: displayText, audioUrl, audioType })
  planning.value = true
  startPlanningProgressFlow(targetPage)
  let planningResponse = null

  try {
    if (targetPage === 'qa') {
      const assistantMessage = reactive({ role: 'assistant', text: '', isStreaming: true })
      const streamDisplay = createSmoothTextStream(assistantMessage)
      messages.value.push(assistantMessage)
      await streamMessage(sessionId.value || `local_${Date.now()}`, text, (chunk) => {
        streamDisplay.push(chunk)
      })
      await streamDisplay.finish()
    } else {
      const response = await streamPlanMessage(
        sessionId.value || `local_${Date.now()}`,
        text,
        applyPlanningProgressEvent
      )
      planningResponse = response
      requirements.value = response.requirements || requirements.value
      applyRecommendationPayload(response)

      // ── 优先使用后端返回的真实行程，不可用时用模板兜底 ──
      const backendItinerary = response.itinerary || response.data?.itinerary
      console.log('🔍 DEBUG response.itinerary:', backendItinerary ? `days=${backendItinerary.days?.length}, items=${backendItinerary.days?.[0]?.items?.length}` : 'null/undefined')
      console.log('🔍 DEBUG response 顶层 keys:', Object.keys(response).join(', '))
      if (backendItinerary && backendItinerary.days && backendItinerary.days.length > 0) {
        applyBackendItinerary(backendItinerary)
        currentItineraryId.value = backendItinerary.itinerary_id || ''
        baseVersion.value = backendItinerary.version || 1
        savedItinerary.value = true
        currentItineraryPayload.value = backendItinerary  // 缓存原始行程供智能修改使用
        syncBudgetFromItineraryDays()
      } else {
        syncItineraryDays(text)
        syncBudgetFromItineraryDays()
      }

      hasPlan.value = true
      saveCurrentTripHistory()
    }
    updatePlanningProgressFromResult(targetPage === 'qa' ? null : planningResponse)
    activePage.value = targetPage
  } catch (error) {
    console.error('🔍 DEBUG submitPromptText 异常:', error.message || error, error.stack)
    console.error('🔍 DEBUG 当前状态 — targetPage:', targetPage, 'hasPlan:', hasPlan.value, 'planningResponse:', planningResponse ? '有值' : 'null')
    apiError.value = error.message
    if (targetPage === 'qa') messages.value.push({
      role: 'assistant',
      text: '问答暂时没有返回结果，请稍后再试。'
    })
    if (targetPage !== 'qa') {
      syncItineraryDays(text)
      hasPlan.value = true
      saveCurrentTripHistory()
    }
    updatePlanningProgressFromResult(null, targetPage === 'qa' ? 'api' : 'demo')
    activePage.value = targetPage
  } finally {
    planning.value = false
  }
}

async function toggleVoiceInput(scene = 'plan') {
  if (voiceRecording.value) {
    stopVoiceInput()
    return
  }
  await startVoiceInput(scene)
}

async function startVoiceInput(scene = 'plan') {
  if (planning.value || voiceRecording.value) return
  voiceError.value = ''
  voiceHint.value = ''
  voiceScene.value = scene

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    voiceError.value = '\u5f53\u524d\u6d4f\u89c8\u5668\u4e0d\u652f\u6301\u5f55\u97f3\uff0c\u8bf7\u7528 Chrome \u6216 Edge\u3002'
    return
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    voiceChunks = []
    const mimeType = supportedVoiceMimeType()
    voiceRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    voiceRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        voiceChunks.push(event.data)
      }
    }
    voiceRecorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop())
      const audioBlob = new Blob(voiceChunks, { type: voiceRecorder?.mimeType || 'audio/webm' })
      voiceRecorder = null
      voiceRecording.value = false
      await submitVoiceBlob(audioBlob, scene)
    }
    voiceRecorder.start()
    voiceRecording.value = true
  } catch (error) {
    voiceError.value = '\u65e0\u6cd5\u5f00\u542f\u9ea6\u514b\u98ce\uff0c\u8bf7\u68c0\u67e5\u6d4f\u89c8\u5668\u6743\u9650\u3002'
    voiceRecording.value = false
  }
}

function stopVoiceInput() {
  if (voiceRecorder && voiceRecorder.state !== 'inactive') {
    voiceRecorder.stop()
  }
}

async function submitVoiceBlob(audioBlob, scene) {
  if (!audioBlob.size) {
    voiceError.value = '\u6ca1\u6709\u5f55\u5230\u58f0\u97f3\uff0c\u8bf7\u91cd\u65b0\u5f55\u5236\u3002'
    return
  }
  planning.value = true
  const audioUrl = URL.createObjectURL(audioBlob)
  voiceObjectUrls.push(audioUrl)
  try {
    const data = await understandVoice({
      sessionId: sessionId.value || 'demo_session',
      scene,
      audioBlob,
      clientHint: ''
    })
    planning.value = false
    const targetPage = scene === 'qa' ? 'qa' : 'trip'
    if (!data.understood_text) {
      messages.value.push({
        role: 'user',
        text: data.display_text || '\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u8f93\u5165',
        audioUrl,
        audioType: audioBlob.type || 'audio/webm'
      })
      messages.value.push({
        role: 'assistant',
        text: data.asr_error ? `?????????????${data.asr_error}` : '\u8fd9\u6761\u8bed\u97f3\u6211\u6ca1\u6709\u542c\u6e05\uff0c\u8bf7\u518d\u5f55\u4e00\u6b21\uff0c\u6216\u8005\u76f4\u63a5\u7528\u6587\u5b57\u8f93\u5165\u3002'
      })
      activePage.value = targetPage
      return
    }
    await submitPromptText(
      data.understood_text,
      targetPage,
      data.display_text || '\u5df2\u53d1\u9001\u4e00\u6761\u8bed\u97f3\u8f93\u5165',
      audioUrl,
      audioBlob.type || 'audio/webm'
    )
  } catch (error) {
    planning.value = false
    voiceError.value = error.message || '\u8bed\u97f3\u7406\u89e3\u5931\u8d25'
  }
}

function startHiddenSpeechRecognition() {
  return false
}

function stopHiddenSpeechRecognition() {
  try {
    voiceRecognition?.stop?.()
  } catch (error) {
    // 浏览器可能已经自动停止，忽略即可。
  }
  voiceRecognition = null
}

function supportedVoiceMimeType() {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || ''
}

function applyRecommendationPayload(response) {
  recommendationResult.value = response.recommendation_result || null
  recommendedRoutes.value = Array.isArray(response.routes)
    ? response.routes
    : Array.isArray(response.recommendation_result?.routes)
      ? response.recommendation_result.routes
      : []

  if (response.map_resources?.resources?.length) {
    mapResources.value = mergeMapResourceDetails(
      response.map_resources.resources,
      recommendationResult.value
    )
    mapError.value = response.map_resources.warnings?.length
      ? response.map_resources.warnings.join('；')
      : ''
    return
  }

  const resources = resourcesFromRecommendationResult(recommendationResult.value)
  if (resources.length) {
    mapResources.value = resources
    mapError.value = '地图资源接口暂未返回，当前使用推荐结果中的坐标展示。'
  }
}

function applyItineraryPayload(response, fallbackText = '') {
  currentItineraryPayload.value = response.itinerary || null
  if (currentItineraryPayload.value && applyGeneratedItinerary(currentItineraryPayload.value)) {
    syncBudgetFromItineraryDays()
    return
  }
  syncItineraryDays(fallbackText)
  syncBudgetFromItineraryDays()
}

function fallbackRecommendationResources() {
  const resources = resourcesFromRecommendationResult(recommendationResult.value)
  return resources.length ? resources : getMockMapResources()
}

function mergeMapResourceDetails(resources = [], result = null) {
  const placeMap = new Map(
    recommendationPlaces(result).map((place) => [place.place_id, place])
  )
  return resources.map((resource) => {
    const place = placeMap.get(resource.place_id)
    return normalizeMapResource({
      ...resource,
      price: resource.price ?? place?.price ?? null,
      open_time: resource.open_time ?? place?.open_time ?? '',
      tags: resource.tags?.length ? resource.tags : [...(place?.tags || [])],
      short_description: resource.short_description || place?.description || '暂无地点摘要',
      recommend_reason: resource.recommend_reason || result?.policy_summary || '推荐资源适合本次旅行需求。'
    })
  })
}

function resourcesFromRecommendationResult(result) {
  return recommendationPlaces(result).map((place) => normalizeMapResource({
    place_id: place.place_id,
    name: place.name,
    place_type: place.place_type,
    longitude: place.longitude ?? place.coordinate?.longitude,
    latitude: place.latitude ?? place.coordinate?.latitude,
    address: place.address || `${place.city || ''}${place.area || ''}${place.name || ''}`,
    short_description: place.short_description || place.description || '暂无地点摘要',
    recommend_reason: result?.policy_summary || '推荐资源适合本次旅行需求。',
    verified: place.verified !== false,
    warning: place.warning || null,
    price: place.price ?? null,
    open_time: place.open_time || '',
    tags: Array.isArray(place.tags) ? [...place.tags] : []
  }))
}

function recommendationPlaces(result) {
  if (!result) return []
  return [
    ...(Array.isArray(result.hotels) ? result.hotels : []),
    ...(Array.isArray(result.attractions) ? result.attractions : []),
    ...(Array.isArray(result.restaurants) ? result.restaurants : [])
  ]
}

function normalizeMapResource(resource) {
  const longitude = Number(resource.longitude)
  const latitude = Number(resource.latitude)
  return {
    ...resource,
    longitude: Number.isFinite(longitude) ? longitude : null,
    latitude: Number.isFinite(latitude) ? latitude : null,
    verified: resource.verified !== false,
    tags: Array.isArray(resource.tags) ? [...resource.tags] : []
  }
}

function applyGeneratedItinerary(itinerary) {
  if (!itinerary || !Array.isArray(itinerary.days) || !itinerary.days.length) return false

  const placeMap = new Map(recommendationPlaces(recommendationResult.value).map((place) => [place.place_id, place]))
  const hotelName = placeMap.get(itinerary.hotel_place_id)?.name || '推荐住宿'

  itineraryDays.value = itinerary.days.map((day, index) => {
    const items = Array.isArray(day.items) ? day.items : []
    const uiItems = items.map((item) => generatedItemToUi(item, placeMap, hotelName))
    return {
      day: Number(day.day) || index + 1,
      title: buildGeneratedDayTitle(uiItems, index + 1),
      date: day.date || '生成日期',
      walking: formatDistance(day.walking_distance_m),
      cost: Math.round(Number(day.daily_cost) || 0),
      hotel: hotelName,
      routeTime: estimateRouteTime(uiItems),
      area: buildGeneratedArea(uiItems),
      highlights: buildGeneratedHighlights(uiItems),
      items: uiItems.length ? uiItems : [{
        time: day.start_time || '09:00',
        title: '当天安排生成中',
        tag: '规划',
        desc: '后端已返回当天结构，但暂时没有具体地点。',
        cost: 0,
        route: '等待成员三补充详细时间线'
      }]
    }
  })

  activeDay.value = itineraryDays.value[0]?.day || 1
  return true
}

function generatedItemToUi(item, placeMap, hotelName) {
  const place = item.place_id ? placeMap.get(item.place_id) : null
  const typeLabel = itemTypeLabel(item.item_type)
  const title = place?.name || item.note || (item.item_type === 'return' ? `返回${hotelName}` : typeLabel)
  const desc = place?.short_description
    || place?.description
    || place?.recommendation_reason
    || place?.recommend_reason
    || item.note
    || '根据当前需求自动安排，可继续输入偏好进行调整。'
  const route = buildItemRouteText(item)
  return {
    place_id: item.place_id || place?.place_id || '',
    item_type: item.item_type || '',
    place_type: place?.place_type || item.item_type || '',
    longitude: place?.longitude ?? place?.lng ?? item.longitude ?? item.lng ?? null,
    latitude: place?.latitude ?? place?.lat ?? item.latitude ?? item.lat ?? null,
    address: place?.address || item.address || '',
    open_time: place?.open_time || '',
    verified: place?.verified !== false,
    time: item.start_time || '待定',
    title,
    tag: typeLabel,
    desc,
    cost: Math.round(Number(item.total_cost ?? item.cost_per_person) || 0),
    route,
    detail: {
      image: getPlaceImage({
        place_id: item.place_id || place?.place_id,
        item_type: item.item_type,
        place_type: place?.place_type,
        title
      }),
      title,
      desc,
      tips: [
        item.end_time ? `${item.start_time || '待定'}-${item.end_time}` : '时间可调整',
        route,
        place?.address || '可在路线地图中查看位置'
      ].filter(Boolean)
    }
  }
}

function normalizePicturePlaceId(placeId = '') {
  const id = String(placeId || '').trim()
  const oldMatch = id.match(/^(attraction|restaurant|hotel)_(\d+)$/)
  if (!oldMatch) return id
  const prefix = oldMatch[1] === 'attraction' ? 'tj_place' : `tj_${oldMatch[1]}`
  return `${prefix}_${oldMatch[2].padStart(3, '0')}`
}

function localPictureById(placeId = '') {
  const id = normalizePicturePlaceId(placeId)
  if (!id) return ''
  const folders = id.startsWith('tj_place_')
    ? ['attractions/attractions']
    : id.startsWith('tj_restaurant_')
      ? ['resturant']
      : id.startsWith('tj_hotel_')
        ? ['hotels']
        : ['attractions/attractions', 'resturant', 'hotels']
  const extensions = ['png', 'jpg', 'jpeg']
  for (const folder of folders) {
    for (const ext of extensions) {
      const asset = localPictures[`../pictures/${folder}/${id}.${ext}`]
      if (asset) return asset
    }
  }
  return ''
}

function localPictureIdByTitle(title = '') {
  const text = String(title || '')
  const titleMap = [
    ['天津博物馆', 'tj_place_001'],
    ['天津自然博物馆', 'tj_place_002'],
    ['天津科学技术馆', 'tj_place_003'],
    ['天塔湖', 'tj_place_004'],
    ['五大道', 'tj_place_005'],
    ['民园广场', 'tj_place_006'],
    ['瓷房子', 'tj_place_007'],
    ['张学良故居', 'tj_place_008'],
    ['意式风情区', 'tj_place_009'],
    ['海河夜景', 'tj_place_010'],
    ['天津之眼', 'tj_place_011'],
    ['古文化街', 'tj_place_012'],
    ['鼓楼', 'tj_place_013'],
    ['狗不理', 'tj_restaurant_001'],
    ['99优选酒店', 'tj_hotel_015'],
    ['全季酒店', 'tj_hotel_013'],
    ['汉庭酒店', 'tj_hotel_014'],
    ['如家酒店', 'tj_hotel_016']
  ]
  const matched = titleMap.find(([name]) => text.includes(name))
  return matched?.[1] || ''
}

function getPlaceImage({ place_id = '', item_type = '', place_type = '', title = '' } = {}) {
  if (['departure', 'return', 'transport'].includes(item_type)) {
    return generatedPlaceImage(item_type)
  }
  return localPictureById(place_id)
    || localPictureById(localPictureIdByTitle(title))
    || generatedPlaceImage(place_type || item_type)
}

function itemTypeLabel(type) {
  const labels = {
    departure: '出发',
    transport: '交通',
    attraction: '景点',
    lunch: '午餐',
    dinner: '晚餐',
    hotel: '住宿',
    rest: '休息',
    return: '返程'
  }
  return labels[type] || '安排'
}

function generatedPlaceImage(type) {
  if (type === 'lunch' || type === 'dinner') {
    return 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=900&q=80'
  }
  if (type === 'hotel') {
    return 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80'
  }
  return 'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80'
}

function buildItemRouteText(item) {
  const duration = Number(item.duration_minutes) || 0
  const timeText = item.end_time ? `${item.start_time || '待定'}-${item.end_time}` : '时间待定'
  if (item.item_type === 'departure') return item.note || '从住宿点出发'
  if (item.item_type === 'return') return item.note || '返回住宿点或取行李'
  return duration ? `${timeText} · 预计停留 ${duration} 分钟` : timeText
}

function buildGeneratedDayTitle(items, fallbackDay) {
  const mainStops = items
    .filter((item) => !['出发', '返程', '交通'].includes(item.tag))
    .map((item) => item.title)
    .slice(0, 2)
  return mainStops.length ? mainStops.join(' · ') : `第 ${fallbackDay} 天行程`
}

function buildGeneratedArea(items) {
  const tags = [...new Set(items.map((item) => item.tag).filter((tag) => !['出发', '返程'].includes(tag)))]
  return tags.slice(0, 3).join(' · ') || '天津'
}

function buildGeneratedHighlights(items) {
  const stops = items.filter((item) => !['出发', '返程', '交通'].includes(item.tag)).slice(0, 3)
  if (!stops.length) return ['按用户需求生成', '可继续对话修改', '保留时间弹性']
  return stops.map((item) => `${item.time} ${item.title}`)
}

function estimateRouteTime(items) {
  const minutes = items.reduce((sum, item) => {
    const match = String(item.route || '').match(/停留\s*(\d+)\s*分钟/)
    return sum + (match ? Number(match[1]) : 0)
  }, 0)
  return minutes ? `${minutes} 分钟` : '已预留'
}

function formatDistance(value) {
  const meters = Number(value)
  if (!Number.isFinite(meters) || meters <= 0) return '待校验'
  if (meters < 1000) return `${Math.round(meters)} 米`
  return `${(meters / 1000).toFixed(1)} 公里`
}

function parseDistanceMeters(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? Math.max(0, value) : 0
  const text = String(value || '')
  let total = 0
  const matches = text.matchAll(/([\d.]+)\s*(公里|千米|km|KM|米|m)/g)
  for (const match of matches) {
    const amount = Number(match[1])
    if (!Number.isFinite(amount)) continue
    const unit = match[2].toLowerCase()
    total += unit === '米' || unit === 'm' ? amount : amount * 1000
  }
  return Math.round(total)
}

function parseRouteMinutes(value) {
  const text = String(value || '')
  let total = 0
  const matches = text.matchAll(/([\d.]+)\s*分钟/g)
  for (const match of matches) {
    const amount = Number(match[1])
    if (Number.isFinite(amount)) total += amount
  }
  return total
}

function isWalkingRouteText(value) {
  const text = String(value || '')
  return /步行|徒步|散步|漫步|游览|逛/.test(text)
}

function deriveDayWalkingDistanceMeters(day) {
  const explicit = Number(day?.walking_distance_m)
  if (Number.isFinite(explicit) && explicit > 0) return Math.round(explicit)

  const itemTotal = (day?.items || []).reduce((sum, item) => {
    const itemExplicit = Number(item?.walking_distance_m)
    if (Number.isFinite(itemExplicit) && itemExplicit > 0) return sum + itemExplicit

    const routeText = String(item?.route || '')
    if (!isWalkingRouteText(routeText)) return sum

    const distance = parseDistanceMeters(routeText)
    if (distance > 0) return sum + distance

    const minutes = parseRouteMinutes(routeText)
    return sum + Math.round(minutes * 80)
  }, 0)
  if (itemTotal > 0) return Math.round(itemTotal)

  return parseDistanceMeters(day?.walking)
}

function syncBudgetFromGeneratedItinerary(itinerary) {
  const days = Array.isArray(itinerary.days) ? itinerary.days : []
  const mealTypes = new Set(['lunch', 'dinner'])
  const totals = days.flatMap((day) => day.items || []).reduce((acc, item) => {
    const cost = Number(item.total_cost) || 0
    if (mealTypes.has(item.item_type)) acc.food += cost
    else if (item.item_type === 'attraction') acc.ticket += cost
    else if (['transport', 'return', 'departure'].includes(item.item_type)) acc.transport += cost
    else acc.other += cost
    return acc
  }, { ticket: 0, food: 0, transport: 0, other: 0 })

  budget.value = [
    { label: '门票', value: Math.round(totals.ticket), color: '#14b8a6' },
    { label: '餐饮', value: Math.round(totals.food), color: '#f59e0b' },
    { label: '交通', value: Math.round(totals.transport), color: '#ef6f88' },
    { label: '其他', value: Math.round(totals.other), color: '#5b6cff' }
  ]
}

function budgetCategoryForItem(item) {
  const tag = String(item?.tag || '')
  const type = String(item?.item_type || '')
  const title = String(item?.title || '')
  const route = String(item?.route || '')

  if (tag === '住宿' || type === 'hotel' || title.includes('酒店')) return 'hotel'
  if (tag === '餐饮' || ['lunch', 'dinner', 'food'].includes(type)) return 'food'
  if (
    ['交通', '跨区交通', '出发准备', '返程'].includes(tag)
    || ['transport', 'departure', 'return'].includes(type)
    || /地铁|打车|公交|城际|出租|换乘|返回|出发/.test(route)
  ) return 'transport'
  if (tagCategory[tag] === 'attraction' || type === 'attraction') return 'ticket'
  return 'other'
}

function syncBudgetFromItineraryDays(days = itineraryDays.value) {
  const totals = { hotel: 0, ticket: 0, food: 0, transport: 0, other: 0 }
  const stats = { hotel: 0, ticket: 0, food: 0, transport: 0, attraction: 0 }

  ;(days || []).forEach((day) => {
    let dayCost = 0
    ;(day.items || []).forEach((item) => {
      const category = budgetCategoryForItem(item)
      if (stats[category] !== undefined) stats[category] += 1
      if (category === 'ticket') stats.attraction += 1
      const cost = Number(item?.cost ?? item?.total_cost) || 0
      dayCost += cost
      if (cost <= 0) return
      totals[category] += cost
    })
    day.cost = Math.round(dayCost)
    day.walking = formatDistance(deriveDayWalkingDistanceMeters(day))
  })

  budget.value = [
    { label: '酒店', value: Math.round(totals.hotel), color: '#5b6cff' },
    { label: '门票', value: Math.round(totals.ticket), color: '#14b8a6' },
    { label: '餐饮', value: Math.round(totals.food), color: '#f59e0b' },
    { label: '交通', value: Math.round(totals.transport), color: '#ef6f88' },
  ]
}

function routeProgressText() {
  if (amapRouteCount.value) {
    return `已返回 ${amapRouteCount.value} 条高德实际路线，等待成员三生成完整行程`
  }
  if (recommendedRoutes.value.length) {
    return '已返回路线事实，但尚未通过高德验证，地图不会按真实路线绘制'
  }
  return '等待行程规划模块生成完整方案'
}

function isVerifiedAmapRoute(route) {
  return route?.source === 'amap' && route?.verified === true && Array.isArray(route.polyline) && route.polyline.length >= 2
}

function fillPrompt(text, page = activePage.value) {
  prompt.value = text
  activePage.value = page
}

function clampTripDays(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 2
  return Math.min(5, Math.max(1, Math.round(number)))
}

function extractDaysFromText(text) {
  const digitMatch = text.match(/([1-5])\s*[天日]/)
  if (digitMatch) return Number(digitMatch[1])

  const chineseDays = {
    一: 1,
    两: 2,
    二: 2,
    三: 3,
    四: 4,
    五: 5
  }
  const chineseMatch = text.match(/([一两二三四五])\s*[天日]/)
  return chineseMatch ? chineseDays[chineseMatch[1]] : null
}

function normalizeRequirementsFromText(text) {
  const detectedDays = extractDaysFromText(text)
  requirements.value.days = clampTripDays(detectedDays || requirements.value.days || 2)

  const budgetMatch = text.match(/预算\s*([0-9]{3,5})\s*元?/)
  if (!requirements.value.total_budget && budgetMatch) {
    requirements.value.total_budget = Number(budgetMatch[1])
  }

  if (!requirements.value.city) {
    requirements.value.city = '天津'
  }
}

/**
 * 将后端返回的 Itinerary 转为前端 itineraryDays 格式
 */
function applyBackendItinerary(backendItinerary) {
  const city = requirements.value.city || '天津'

  itineraryDays.value = (backendItinerary.days || []).map((dayData) => {
    let totalRouteMin = 0
    const items = (dayData.items || []).map((item) => {
      const place = item._place || {}
      const itemType = item.item_type || 'attraction'
      // 优先使用后端计算的路线文本，其次使用地点地址
      const routeText = item.route
        || (item._route_duration_minutes
            ? `约 ${item._route_duration_minutes} 分钟`
            : place.address || '')
      // 累加路线耗时
      const dur = Number(item._route_duration_minutes) || 0
      if (dur > 0 && itemType === 'attraction') totalRouteMin += dur
      const title = (itemType === 'departure' || itemType === 'return')
        ? (item.note || itemType)
        : (place.name || item.note || item.place_id || itemType)
      const desc = cleanItineraryCardDesc(item.note || place.short_description || '')
      return {
        place_id: item.place_id || place.place_id || '',
        item_type: itemType,
        place_type: place.place_type || itemType,
        longitude: place.longitude ?? place.lng ?? item.longitude ?? item.lng ?? null,
        latitude: place.latitude ?? place.lat ?? item.latitude ?? item.lat ?? null,
        address: place.address || item.address || '',
        open_time: place.open_time || '',
        verified: place.verified !== false,
        time: item.start_time || '09:00',
        // departure/return 不显示酒店名，直接用 note（"出发"/"返回酒店"）
        title: cleanItineraryTitle(title),
        tag: typeToTag(itemType, item, place),
        desc,
        ragDesc: place.rag_description || '',
        cost: item.total_cost || 0,
        route: routeText,
        detail: buildItemDetail(item, place, title, desc, routeText),
      }
    })

    const totalCost = dayData.daily_cost || items.reduce((s, it) => s + it.cost, 0)
    const walkingM = dayData.walking_distance_m || 0
    const walkingStr = walkingM >= 1000
      ? `${(walkingM / 1000).toFixed(1)} 公里`
      : `${walkingM} 米`
    const routeTimeStr = totalRouteMin > 0
      ? `${totalRouteMin} 分钟`
      : '待计算'

    return {
      day: dayData.day,
      title: `${city}第${dayData.day}天`,
      date: dayData.date || '2026-07-25',
      walking: walkingStr,
      cost: totalCost,
      hotel: '参考酒店',
      routeTime: routeTimeStr,
      area: city,
      highlights: buildBackendHighlights(items, dayData),
      items,
    }
  })
}

function buildBackendHighlights(uiItems, dayData = {}) {
  const result = recommendationResult.value || {}
  const evidenceList = Array.isArray(result.evidence) ? result.evidence : []
  const evidenceByPlaceId = new Map(
    evidenceList
      .filter((item) => item?.place_id && item.sufficient !== false && item.summary)
      .map((item) => [item.place_id, item])
  )
  const placesById = new Map(
    recommendationPlaces(result)
      .filter((place) => place?.place_id)
      .map((place) => [place.place_id, place])
  )
  const highlights = []

  ;(Array.isArray(dayData.highlights) ? dayData.highlights : []).forEach((item) => {
    appendHighlight(highlights, item)
  })

  ;(dayData.items || []).forEach((item) => {
    const placeId = item.place_id
    const evidence = placeId ? evidenceByPlaceId.get(placeId) : null
    const place = item._place || placesById.get(placeId) || {}
    if (evidence?.summary) {
      appendHighlight(highlights, `${place.name || item.note || placeId}：${evidence.summary}`)
      return
    }

    const reason = place.recommend_reason
      || place.recommendation_reason
      || place.short_description
      || place.description
      || ''
    if (reason && !['departure', 'return', 'transport'].includes(item.item_type)) {
      appendHighlight(highlights, `${place.name || item.note || placeId}：${reason}`)
    }
  })

  if (!highlights.length && result.policy_summary) {
    appendHighlight(highlights, result.policy_summary)
  }

  uiItems
    .filter((item) => !['出发准备', '返程', '跨区交通'].includes(item.tag))
    .slice(0, 3)
    .forEach((item) => {
      appendHighlight(highlights, `${item.time} ${item.title}：${item.desc || item.route}`)
    })

  return highlights.slice(0, 4)
}

function appendHighlight(target, value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text || target.includes(text)) return
  target.push(text.length > 90 ? `${text.slice(0, 90)}...` : text)
}

/** item_type → 前端 tag 映射 */
function typeToTag(itype, item, place) {
  const cats = place.categories || []
  if (itype === 'departure') return '出发准备'
  if (itype === 'return') return '返程'
  if (itype === 'transport') return '跨区交通'
  if (itype === 'lunch' || itype === 'dinner') return '餐饮'
  if (itype === 'rest') return '休整'
  if (itype === 'hotel') return '住宿'
  if (cats.includes('博物馆') || cats.includes('展馆')) return '博物馆'
  if (cats.includes('建筑') || cats.includes('街区')) return '近代建筑'
  if (cats.includes('夜景')) return '夜景'
  if (cats.includes('公园') || cats.includes('自然')) return '城市公园'
  return '景点'
}

function syncItineraryDays(text = '') {
  currentItineraryPayload.value = null
  normalizeRequirementsFromText(text)
  const days = clampTripDays(requirements.value.days)
  const baseDays = defaultItineraryTemplates.slice(0, 2).map((day) => ({
    ...day,
    highlights: [...day.highlights],
    items: day.items.map((item) => ({ ...item }))
  }))
  const generated = [...baseDays]

  for (let index = 3; index <= days; index += 1) {
    const template = extraDayTemplates[index - 3]
    generated.push({
      ...template,
      highlights: [...template.highlights],
      day: index,
      date: '演示日期',
      items: template.items.map((item) => ({ ...item }))
    })
  }

  itineraryDays.value = generated.slice(0, days).map((day, index) => ({
    ...day,
    highlights: [...day.highlights],
    day: index + 1,
    items: day.items.map((item) => ({ ...item }))
  }))

  activeDay.value = 1
  savedItinerary.value = false // 新行程需要重新保存
}

function saveCurrentTripHistory() {
  const city = requirements.value.city || '天津'
  const days = requirements.value.days || itineraryDays.value.length
  const title = `${city}${days}日自由行`
  if (tripHistory.value.some((item) => item.title === title && item.status === '当前方案')) return

  tripHistory.value = [
    {
      id: `tj-${Date.now()}`,
      title,
      date: new Date().toISOString().slice(0, 10),
      tags: requirements.value.interests?.length ? requirements.value.interests : ['待完善偏好'],
      status: '当前方案',
      budget: requirements.value.total_budget || totalSpent.value
    },
    ...tripHistory.value
  ]
}

function formatMessage(text) {
  if (!text) return ''
  let safe = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')

  safe = safe
    .replace(/\r\n/g, '\n')
    .replace(/([。！？；])\s+(\d+\.\s*)/g, '$1\n$2')
    .replace(/(\S)\s+(\d+\.\s*(?:<strong>|[\u4e00-\u9fa5A-Za-z]))/g, '$1\n$2')
    .replace(/\s+[-•]\s+/g, '\n- ')

  const lines = safe.split(/\n+/).map((line) => line.trim()).filter(Boolean)
  let html = ''
  let inList = false
  let inBulletList = false

  const closeLists = () => {
    if (inList) {
      html += '</ol>'
      inList = false
    }
    if (inBulletList) {
      html += '</ul>'
      inBulletList = false
    }
  }

  for (const line of lines) {
    const ordered = line.match(/^(\d+)\.\s*(.*)$/)
    const bullet = line.match(/^[-•]\s*(.*)$/)
    if (ordered) {
      if (inBulletList) {
        html += '</ul>'
        inBulletList = false
      }
      if (!inList) {
        html += '<ol>'
        inList = true
      }
      html += `<li>${ordered[2]}</li>`
    } else if (bullet) {
      if (inList) {
        html += '</ol>'
        inList = false
      }
      if (!inBulletList) {
        html += '<ul>'
        inBulletList = true
      }
      html += `<li>${bullet[1]}</li>`
    } else {
      closeLists()
      html += `<p>${line}</p>`
    }
  }

  closeLists()
  return html
}

function openPlaceDetail(item) {
  const detail = item.detail || placeDetails[item.title] || {
    title: item.title,
    desc: item.ragDesc || item.desc,
    tips: [item.tag, item.route, '可根据天气、体力和预算继续调整']
  }
  selectedPlace.value = {
    ...detail,
    image: getPlaceImage(item) || detail.image
  }
}

/**
 * 保存当前演示行程到后端，返回 itinerary_id
 */
async function saveCurrentItineraryToBackend() {
  if (savedItinerary.value && currentItineraryId.value) return currentItineraryId.value

  const demoItinerary = {
    itinerary_id: `demo_${Date.now()}`,
    session_id: sessionId.value || 'demo_session',
    version: 1,
    days: itineraryDays.value.map((day, di) => ({
      day: day.day,
      date: /^\d{4}-\d{2}-\d{2}$/.test(day.date) ? day.date : '2026-07-25',
      items: day.items.map((item, ii) => ({
        item_id: `day${day.day}_item_${String(ii).padStart(3, '0')}`,
        day: day.day,
        item_type: item.tag === '餐饮' ? 'lunch'
          : item.tag === '夜景' ? 'attraction'
          : item.tag === '近代建筑' || item.tag === '城市地标' || item.tag === '名人故居' || item.tag === '街区文化' || item.tag === '传统街区' || item.tag === '民俗文化' || item.tag === '博物馆' || item.tag === '建筑打卡' ? 'attraction'
          : item.tag === '城市漫游' || item.tag === '城市休闲' || item.tag === '休整' ? 'rest'
          : item.tag === '出发准备' || item.tag === '返程' || item.tag === '跨区交通' ? 'transport'
          : 'attraction',
        place_id: `place_${day.day}_${ii}`,
        start_time: item.time || '09:00',
        end_time: calcEndTime(item.time, 60),
        duration_minutes: 60,
        total_cost: item.cost || 0,
        locked: false,
        // 仅保存描述信息，不拼标题（避免修改循环中标题-描述反复叠加）
        note: item.desc || item.title || '',
      })),
      daily_cost: day.cost || 0,
      walking_distance_m: parseWalkingDistance(day.walking || '0'),
      start_time: day.items?.[0]?.time || '09:00',
      end_time: day.items?.[day.items.length - 1]?.time || '18:00',
    })),
    total_cost: itineraryDays.value.reduce((sum, d) => sum + (d.cost || 0), 0),
    status: 'draft',
  }

  try {
    const resp = await fetch('/api/v1/itineraries/save-demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(demoItinerary),
    })
    const json = await resp.json()
    if (json.success && json.data) {
      currentItineraryId.value = json.data.itinerary_id
      baseVersion.value = json.data.version
      savedItinerary.value = true
      return currentItineraryId.value
    }
    // Fallback: 用生成的 id 凑合
    currentItineraryId.value = demoItinerary.itinerary_id
    savedItinerary.value = true
    return currentItineraryId.value
  } catch (err) {
    console.warn('save-demo 失败，使用本地 ID 兜底:', err.message)
    currentItineraryId.value = demoItinerary.itinerary_id
    savedItinerary.value = true
    return currentItineraryId.value
  }
}

function calcEndTime(start, durationMin) {
  if (!start) return '10:00'
  const [h, m] = start.split(':').map(Number)
  const total = h * 60 + m + durationMin
  return `${String(Math.floor(total / 60) % 24).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

function parseWalkingDistance(str) {
  const meters = parseDistanceMeters(str)
  return meters > 0 ? meters : 0
}

function extractModifyAction(text) {
  const lower = text.toLowerCase()
  if (lower.includes('室内') || lower.includes('下雨') || lower.includes('雨天') || lower.includes('天气')) return 'change_to_indoor'
  if (lower.includes('累') || lower.includes('减少步行') || lower.includes('少走') || lower.includes('近点') || lower.includes('近一点') || lower.includes('距离近') || lower.includes('轻松') || lower.includes('体力') || lower.includes('疲劳')) return 'reduce_walking'
  if (lower.includes('替换') || lower.includes('换掉') || lower.includes('换成') || lower.includes('改成') || lower.includes('不喜欢') || lower.includes('不想') || lower.includes('不感')) return 'replace_attraction'
  if (lower.includes('预算') || lower.includes('省钱') || lower.includes('加钱') || lower.includes('超支')) return 'change_budget'
  return 'replace_attraction'
}

function extractTargetDay(text) {
  // 明确写了"第X天"
  const match = text.match(/第\s*([一二三四五六七八九十\d]+)\s*天/)
  if (match) {
    const numMap = { '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10 }
    const day = numMap[match[1]] || parseInt(match[1], 10)
    return isNaN(day) ? null : day
  }
  // 没写天数 → 根据关键词匹配行程项所在的天
  for (const day of itineraryDays.value) {
    for (const item of day.items) {
      if (item.title.includes('博物') && text.includes('博物')) return day.day
      if (item.title.includes('古文化') && text.includes('古文化')) return day.day
      if (item.title.includes('海河') && text.includes('海河')) return day.day
      if (item.tag === '博物馆' && (text.includes('博物') || text.includes('展馆'))) return day.day
      if (item.title.includes('瓷房子') && text.includes('瓷房子')) return day.day
      if (item.title.includes('五大') && text.includes('五大')) return day.day
    }
  }
  // 完全没线索 → 默认第 1 天
  return itineraryDays.value.length > 0 ? itineraryDays.value[0].day : null
}

function cloneItineraryDays(days) {
  return (days || []).map((day) => ({
    ...day,
    highlights: Array.isArray(day.highlights) ? [...day.highlights] : [],
    items: Array.isArray(day.items)
      ? day.items.map((item) => ({
          ...item,
          detail: item.detail && typeof item.detail === 'object'
            ? {
                ...item.detail,
                tips: Array.isArray(item.detail.tips) ? [...item.detail.tips] : item.detail.tips,
              }
            : item.detail,
        }))
      : [],
  }))
}

function cleanItineraryTitle(value, fallback = '行程项') {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text) return fallback
  return text.length > 32 ? text.slice(0, 32).replace(/[，。；：、]\s*$/, '') : text
}

function cleanItineraryCardDesc(value, fallback = '') {
  const text = String(value || '')
    .replace(/\s+/g, ' ')
    .replace(/^(它的候选价值|酒店记录的设施与服务|当前参考价格|这使它可以作为|点击.*?可以解释).*?[。；]/g, '')
    .trim()
  if (!text) return fallback
  const firstSentences = text.split(/(?<=[。！？；])/).filter(Boolean).slice(0, 2).join('')
  const result = firstSentences || text
  return result.length > 86 ? `${result.slice(0, 86).replace(/[，。；：、]\s*$/, '')}...` : result
}

function buildItemDetail(item, place, title, desc, route = '') {
  return {
    image: place?.image || place?.image_url || getPlaceImage({
      place_id: item?.place_id || place?.place_id,
      item_type: item?.item_type,
      place_type: place?.place_type,
      title: place?.name || title
    }),
    title: cleanItineraryTitle(place?.name || title),
    desc: cleanItineraryCardDesc(place?.rag_description || place?.short_description || desc || item?.note || '', desc || '暂无地点摘要'),
    tips: [
      item?.tag || typeToTag(item?.item_type || 'attraction', item || {}, place || {}),
      route || item?.route || place?.address || '',
      place?.open_time || '',
      place?.recommend_reason || item?.note || '',
    ].filter(Boolean).slice(0, 4),
  }
}

function buildAdjustmentPreviewChanges(beforeDays, afterDays, fallbackDay, requestText = '') {
  const changes = []
  const beforeByDay = new Map((beforeDays || []).map((day) => [Number(day.day), day]))

  for (const afterDay of afterDays || []) {
    const dayNumber = Number(afterDay.day)
    if (fallbackDay && dayNumber !== Number(fallbackDay)) continue
    const beforeDay = beforeByDay.get(dayNumber)
    const beforeItems = beforeDay?.items || []
    const afterItems = afterDay.items || []
    const maxLen = Math.max(beforeItems.length, afterItems.length)

    for (let index = 0; index < maxLen; index += 1) {
      const before = beforeItems[index]
      const after = afterItems[index]
      if (!after || skipTags.includes(after.tag)) continue

      if (!before) {
        changes.push({
          label: `第 ${dayNumber} 天新增`,
          from: '新增安排',
          to: `${after.time} ${after.title}`,
          why: cleanItineraryCardDesc(after.desc || requestText, '根据你的修改要求补充安排'),
        })
      } else if (before.title !== after.title || before.time !== after.time) {
        const changedBits = []
        if (before.time !== after.time) changedBits.push(`${before.time} 调整到 ${after.time}`)
        if (cleanItineraryTitle(before.title) !== cleanItineraryTitle(after.title)) {
          changedBits.push(`${before.title} 改为 ${after.title}`)
        }
        if (!changedBits.length) continue
        changes.push({
          label: `第 ${dayNumber} 天调整`,
          from: `${before.time} ${before.title}`,
          to: changedBits.join('，'),
          why: cleanItineraryCardDesc(after.desc || requestText, '根据天气、体力或偏好变化调整'),
        })
      }

      if (changes.length >= 3) return changes
    }
  }

  return changes.slice(0, 3)
}

/** 行程项标签 → 类别映射 */
const tagCategory = {
  '近代建筑': 'attraction', '城市地标': 'attraction', '名人故居': 'attraction',
  '街区文化': 'attraction', '传统街区': 'attraction', '民俗文化': 'attraction',
  '博物馆': 'attraction', '建筑打卡': 'attraction', '夜景': 'attraction',
  '海边风光': 'attraction', '城市公园': 'attraction', '传统文化': 'attraction',
  '校园周边': 'attraction', '文化场馆': 'attraction',
  '餐饮': 'food',
  '城市漫游': 'rest', '城市休闲': 'rest', '休整': 'rest',
}
const skipTags = ['出发准备', '返程', '跨区交通']
const outdoorAdjustTags = ['近代建筑', '城市地标', '名人故居', '街区文化', '传统街区', '民俗文化', '夜景', '海边风光', '城市公园', '建筑打卡', '城市漫游', '城市休闲']
const indoorReplacementPool = [
  {
    title: '天津博物馆',
    tag: '博物馆',
    desc: '改为室内展馆，雨天也能稳定游览，适合补充天津城市历史内容。',
    cost: 0,
    route: '同城地铁/打车衔接',
  },
  {
    title: '天津美术馆',
    tag: '文化场馆',
    desc: '改为室内艺术展馆，减少露天停留，适合雨天或体力下降时段。',
    cost: 0,
    route: '与文化中心区域顺路衔接',
  },
  {
    title: '西岸艺术馆',
    tag: '文化场馆',
    desc: '改为室内观展和短休，降低天气影响，也方便控制步行强度。',
    cost: 50,
    route: '打车或地铁约 15-25 分钟',
  },
  {
    title: '滨海新区图书馆',
    tag: '建筑打卡',
    desc: '改为室内建筑空间，适合拍照、避雨和放慢节奏。',
    cost: 0,
    route: '适合滨海方向行程替代',
  },
  {
    title: '南开大悦城室内休息',
    tag: '休整',
    desc: '改为室内商圈休整，可顺便用餐和补给，避免雨天连续步行。',
    cost: 80,
    route: '地铁/打车衔接',
  },
]
const attractionReplacementPool = [
  {
    title: '梁启超纪念馆',
    tag: '名人故居',
    desc: '替换为近代人物历史景点，游览强度适中，也能补充天津文化内容。',
    cost: 10,
    route: '同城地铁/打车衔接',
  },
  {
    title: '鼓楼商业街',
    tag: '传统街区',
    desc: '替换为传统街区与轻餐饮结合的安排，节奏更自由。',
    cost: 0,
    route: '适合与古文化街或南市食品街衔接',
  },
  {
    title: '天津自然博物馆',
    tag: '博物馆',
    desc: '替换为室内展馆，适合亲子、雨天或希望降低步行强度的情况。',
    cost: 0,
    route: '适合文化中心区域衔接',
  },
]

function isOutdoorAdjustmentItem(item) {
  const title = String(item?.title || '')
  const tag = String(item?.tag || '')
  return outdoorAdjustTags.includes(tag)
    || /五大道|民园|海河|天津之眼|津湾|意式|古文化街|瓷房子|张学良|西开|天主教|广场|公园|海边/.test(title)
}

function pickIndoorReplacement(item, usedTitles) {
  const title = String(item?.title || '')
  const preferred = title.includes('海河') || title.includes('天津之眼') || title.includes('津湾')
    ? ['滨海新区图书馆', '天津美术馆', '南开大悦城室内休息']
    : title.includes('五大道') || title.includes('意式') || title.includes('古文化')
      ? ['天津博物馆', '天津美术馆', '西岸艺术馆']
      : ['天津博物馆', '西岸艺术馆', '天津美术馆', '南开大悦城室内休息']

  const ordered = [
    ...preferred.map((name) => indoorReplacementPool.find((item) => item.title === name)).filter(Boolean),
    ...indoorReplacementPool,
  ]
  return ordered.find((option) => option.title !== title && !usedTitles.has(option.title)) || null
}

function pickAttractionReplacement(item, usedTitles) {
  const title = String(item?.title || '')
  return [...attractionReplacementPool, ...indoorReplacementPool]
    .find((option) => option.title !== title && !usedTitles.has(option.title)) || null
}

function buildIntentAdjustedDays(beforeDays, targetDay, requestText, action) {
  const nextDays = cloneItineraryDays(beforeDays)
  const day = nextDays.find((item) => Number(item.day) === Number(targetDay))
  if (!day) return { days: nextDays, changes: [] }

  const usedTitles = new Set((day.items || []).map((item) => item.title).filter(Boolean))
  const changes = []

  day.items = (day.items || []).map((item) => {
    if (changes.length >= 3 || skipTags.includes(item.tag)) return item

    if (action === 'change_to_indoor' && isOutdoorAdjustmentItem(item)) {
      const replacement = pickIndoorReplacement(item, usedTitles)
      if (!replacement) return item
      usedTitles.add(replacement.title)
      changes.push({
        label: `第 ${targetDay} 天调整`,
        from: `${item.time} ${item.title}`,
        to: `${item.time} ${replacement.title}`,
        why: '识别到天气/室内需求，替换为不受雨天影响的室内安排',
      })
      return {
        ...item,
        title: replacement.title,
        tag: replacement.tag,
        desc: replacement.desc,
        cost: Math.min(Number(item.cost) || replacement.cost, replacement.cost),
        route: replacement.route,
        detail: buildItemDetail({ ...item, tag: replacement.tag }, {}, replacement.title, replacement.desc, replacement.route),
        _modified: true,
      }
    }

    if (action === 'reduce_walking' && (isOutdoorAdjustmentItem(item) || tagCategory[item.tag] === 'rest')) {
      const nextRoute = /打车|地铁/.test(item.route || '') ? item.route : '改为打车/地铁衔接，减少连续步行'
      changes.push({
        label: `第 ${targetDay} 天调整`,
        from: `${item.time} ${item.title}`,
        to: `${item.title} 缩短停留并改用交通衔接`,
        why: '识别到体力/少走路需求，优先压缩露天慢行和连续步行',
      })
      return {
        ...item,
        desc: cleanItineraryCardDesc(`${item.desc || ''} 已压缩停留时间，保留核心体验。`, item.desc),
        route: nextRoute,
        _modified: true,
      }
    }

    if (action === 'replace_attraction' && tagCategory[item.tag] === 'attraction') {
      const replacement = pickAttractionReplacement(item, usedTitles)
      if (!replacement) return item
      usedTitles.add(replacement.title)
      changes.push({
        label: `第 ${targetDay} 天调整`,
        from: `${item.time} ${item.title}`,
        to: `${item.time} ${replacement.title}`,
        why: '识别到替换地点意图，选择同类型但不重复的天津候选资源',
      })
      return {
        ...item,
        title: replacement.title,
        tag: replacement.tag,
        desc: replacement.desc,
        cost: replacement.cost,
        route: replacement.route,
        detail: buildItemDetail({ ...item, tag: replacement.tag }, {}, replacement.title, replacement.desc, replacement.route),
        _modified: true,
      }
    }

    if (action === 'change_budget' && Number(item.cost) > 0) {
      const nextCost = Math.max(0, Math.round(Number(item.cost) * 0.7))
      if (nextCost === Number(item.cost)) return item
      changes.push({
        label: `第 ${targetDay} 天调整`,
        from: `${item.time} ${item.title}`,
        to: `预算 ${item.cost} 元降至 ${nextCost} 元`,
        why: '识别到预算变化，优先压缩可替代消费',
      })
      return {
        ...item,
        cost: nextCost,
        desc: cleanItineraryCardDesc(`${item.desc || ''} 已调整为更省预算的选择。`, item.desc),
        _modified: true,
      }
    }

    return item
  })

  day.cost = day.items.reduce((sum, item) => sum + (Number(item.cost) || 0), 0)
  if (action === 'reduce_walking' || action === 'change_to_indoor') {
    const meters = parseWalkingDistance(day.walking || '0')
    if (meters > 0) day.walking = `${Math.max(1, (meters * 0.72 / 1000)).toFixed(1)} 公里`
  }
  day.highlights = changes.length
    ? ['已生成可确认的调整建议', '点击后再替换当前行程', '预算会随行程同步更新']
    : day.highlights

  return { days: nextDays, changes }
}

function buildCurrentItineraryForAdjustment() {
  return {
    itinerary_id: currentItineraryId.value || 'frontend_current',
    session_id: sessionId.value || 'demo_session',
    days: itineraryDays.value.map((day) => ({
      day: day.day,
      title: day.title,
      walking: day.walking,
      cost: day.cost,
      hotel: day.hotel,
      area: day.area,
      items: (day.items || []).map((item) => ({
        time: item.time,
        title: item.title,
        tag: item.tag,
        desc: cleanItineraryCardDesc(item.desc || item.ragDesc || '', item.desc || ''),
        route: item.route || '',
        cost: item.cost || 0,
      })),
    })),
  }
}

async function analyzeSmartAdjustment() {
  const text = smartAdjustInput.value.trim()
  if (!text) return

  pendingAdjustedItinerary.value = null
  appliedAdjustment.value = ''

  const action = extractModifyAction(text)
  const targetDay = extractTargetDay(text)
  const day = targetDay ? itineraryDays.value.find(d => d.day === targetDay) : null

  smartAdjustPreview.value = {
    reason: text,
    ready: false,
    scope: day ? `第 ${day.day} 天` : '当前行程',
    summary: '正在调用调整智能体分析，不会自动覆盖当前行程。',
    affected: day ? day.items.filter(it => !skipTags.includes(it.tag)).map(it => `${it.time} ${it.title}`).slice(0, 6) : [],
    changes: [{ label: '分析中', from: '当前行程', to: '等待智能体建议', why: '根据你的输入和当前每天安排判断影响范围' }],
  }

  try {
    const resp = await previewItineraryAdjustment({
      session_id: sessionId.value || 'demo_session',
      target_day: targetDay,
      action,
      original_text: text,
      current_itinerary: buildCurrentItineraryForAdjustment(),
    })

    if (resp.success && resp.data) {
      const previewChanges = Array.isArray(resp.data.changes) ? resp.data.changes.slice(0, 3) : []
      smartAdjustPreview.value = {
        reason: text,
        ready: Boolean(resp.data.ready && previewChanges.length),
        scope: resp.data.scope || (day ? `第 ${day.day} 天` : '当前行程'),
        summary: resp.data.summary || (previewChanges.length
          ? `智能体已生成 ${previewChanges.length} 条具体修改，点击后才会应用到行程。`
          : '智能体没有返回可直接应用的修改，请换一种说法或指定地点。'),
        affected: day ? day.items.filter(it => !skipTags.includes(it.tag)).map(it => `${it.time} ${it.title}`).slice(0, 5) : [],
        changes: previewChanges,
      }
      appliedAdjustment.value = ''
      return
    }

    smartAdjustPreview.value = {
      reason: text,
      ready: false,
      scope: day ? `第 ${day.day} 天` : '当前行程',
      summary: `智能体分析失败：${resp.message || resp.code || '后端未返回有效建议'}`,
      affected: [],
      changes: [],
    }
  } catch (err) {
    console.warn('调整智能体分析不可用:', err.message)
    smartAdjustPreview.value = {
      reason: text,
      ready: false,
      scope: day ? `第 ${day.day} 天` : '当前行程',
      summary: `调整智能体暂时不可用：${err.message || '请检查后端和模型配置'}`,
      affected: [],
      changes: [],
    }
  }
}

function clearSmartAdjustmentResult() {
  smartAdjustPreview.value = null
  pendingAdjustedItinerary.value = null
  appliedAdjustment.value = ''
  applyingAdjustment.value = false
}

async function applySmartAdjustment() {
  if (!smartAdjustPreview.value) return
  if (applyingAdjustment.value) return
  applyingAdjustment.value = true

  const text = smartAdjustInput.value.trim()
  const action = extractModifyAction(text)
  const targetDay = extractTargetDay(text)
  const startTime = Date.now()

  if (pendingAdjustedItinerary.value?.uiDays?.length) {
    itineraryDays.value = cloneItineraryDays(pendingAdjustedItinerary.value.uiDays)
    currentItineraryPayload.value = pendingAdjustedItinerary.value.itinerary || currentItineraryPayload.value
    syncBudgetFromItineraryDays()
    await loadMapResources()
    baseVersion.value = pendingAdjustedItinerary.value.nextVersion || baseVersion.value + 1
    savedItinerary.value = false
    if (pendingAdjustedItinerary.value.diff) {
      tripDiffData.value = pendingAdjustedItinerary.value.diff
      showDiff.value = true
    }
    const changes = pendingAdjustedItinerary.value.diff?.changes || []
    appliedAdjustment.value = `已应用 AI 调整建议${changes.length ? `：${changes.length} 项变更` : ''}`
    messages.value.push({
      role: 'assistant',
      text: `已根据你的要求更新行程：${text}`,
    })
    pendingAdjustedItinerary.value = null
    smartAdjustPreview.value = null
    applyingAdjustment.value = false
    return
  }

  appliedAdjustment.value = '正在应用智能体建议，后端正在生成新的行程版本...'

  try {
    await saveCurrentItineraryToBackend()
    const resp = await modifyItinerary({
      session_id: sessionId.value || 'demo_session',
      itinerary_id: currentItineraryId.value,
      base_version: baseVersion.value,
      target_day: targetDay,
      action,
      original_text: text,
      new_constraints: {},
      current_itinerary: currentItineraryPayload.value || undefined,
    })

    if (resp.success && resp.data) {
      const { itinerary, diff } = resp.data

      if (itinerary?.days && itinerary.days.length > 0) {
        // 用后端 LLM 返回的行程数据更新前端
        // 保留原始中文名，避免被后端 place_id 覆盖
        const origByDayIdx2 = {}
        for (const origDay of itineraryDays.value) {
          origByDayIdx2[origDay.day] = {}
          origDay.items.forEach((it, idx) => { origByDayIdx2[origDay.day][idx] = it })
        }
        itineraryDays.value = itinerary.days.map((dayData) => {
          const origDay = itineraryDays.value.find(d => d.day === dayData.day) || { items: [], cost: 0, highlights: [] }
          const dayIdxMap = origByDayIdx2[dayData.day] || {}
          const uiItems = (dayData.items || []).map((item, ii) => {
            const origItem = dayIdxMap[ii] || {}
            const place = item._place || {}
            const itemType = item.item_type || 'attraction'
            // 与首次生成完全相同的映射逻辑
            const title = (itemType === 'departure' || itemType === 'return')
              ? (item.note || itemType)
              : (place.name || item.note || item.place_id || itemType)
            const desc = cleanItineraryCardDesc(item.note || place.short_description || '')
            const route = item.route || origItem.route || ''
            return {
              place_id: item.place_id || place.place_id || origItem.place_id || '',
              item_type: itemType,
              place_type: place.place_type || origItem.place_type || itemType,
              longitude: place.longitude ?? place.lng ?? item.longitude ?? item.lng ?? origItem.longitude ?? null,
              latitude: place.latitude ?? place.lat ?? item.latitude ?? item.lat ?? origItem.latitude ?? null,
              address: place.address || item.address || origItem.address || '',
              open_time: place.open_time || origItem.open_time || '',
              verified: place.verified !== false,
              time: item.start_time || origItem.time || '09:00',
              title: cleanItineraryTitle(title),
              tag: typeToTag(itemType, item, place),
              desc,
              ragDesc: place.rag_description || '',
              cost: item.total_cost || origItem.cost || 0,
              route,
              detail: buildItemDetail(item, place, title, desc, route),
            }
          })
          return {
            day: dayData.day,
            title: buildGeneratedDayTitle(uiItems, dayData.day),
            date: /^\d{4}-\d{2}-\d{2}$/.test(dayData.date) ? dayData.date : (origDay.date || '2026-07-25'),
            walking: `${(dayData.walking_distance_m || 0) > 1000 ? ((dayData.walking_distance_m || 0) / 1000).toFixed(1) + ' 公里' : (dayData.walking_distance_m || 0) + ' 米'}`,
            cost: dayData.daily_cost || origDay.cost || 0,
            hotel: origDay.hotel || '参考酒店',
            routeTime: origDay.routeTime || '待计算',
            area: origDay.area || '天津',
            highlights: origDay.highlights || [],
            items: uiItems,
          }
        })
        currentItineraryPayload.value = itinerary
        syncBudgetFromItineraryDays()
        await loadMapResources()
        baseVersion.value = resp.data.itinerary?.version || baseVersion.value + 1
        savedItinerary.value = false
      }

      const changes = diff?.changes || []
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1)
      appliedAdjustment.value = `✅ 后端 AI 已完成调整（${elapsed}s）${changes.length ? `，${changes.length} 项变更` : ''}`
      messages.value.push({
        role: 'assistant',
        text: `已根据你的要求调整行程：${text}\n\n调整类型：${action}\n耗时：${elapsed} 秒`,
      })
      // 显示版本对比
      if (diff) {
        tripDiffData.value = diff
        showDiff.value = true
      }
      smartAdjustPreview.value = null
      applyingAdjustment.value = false
      return
    }
    // 后端返回了但结果异常
    appliedAdjustment.value = `❌ 后端处理异常：${resp.message || resp.code}。请检查后端日志。`
  } catch (err) {
    console.warn('后端智能体调整失败:', err.message)
    appliedAdjustment.value = `后端智能体调整失败：${err.message || '请检查后端和模型配置'}。当前行程没有被替换。`
  }
  applyingAdjustment.value = false
  smartAdjustPreview.value = null
}

/** 后端不可用时的本地兜底方案 — 实际修改 itineraryDays */
function showLocalAdjustment(text, action, targetDay) {
  if (!targetDay) {
    // 如果没提取到天数，默认影响第一天
    targetDay = itineraryDays.value.length > 0 ? itineraryDays.value[0].day : 1
  }

  const dayIndex = itineraryDays.value.findIndex(d => d.day === targetDay)
  if (dayIndex === -1) {
    appliedAdjustment.value = '未找到目标天的行程，请重试。'
    return
  }

  const originalDay = itineraryDays.value[dayIndex]
  const newDay = {
    ...originalDay,
    items: [...originalDay.items],
    highlights: [...(originalDay.highlights || [])],
  }

  // 根据 action 类型修改行程项
  if (action === 'change_to_indoor') {
    // 把户外景点换成室内
    newDay.items = newDay.items.map((item, idx) => {
      const outdoorTags = ['近代建筑', '城市地标', '街区文化', '传统街区', '民俗文化', '夜景', '海边风光']
      if (outdoorTags.includes(item.tag) && item.title !== '酒店出发' && item.title !== '返回酒店') {
        return {
          ...item,
          title: idx === 1 ? '天津博物馆' : idx === 3 ? '西岸艺术馆' : idx === 5 ? '南开大悦城休息' : item.title,
          tag: '博物馆',
          desc: /\d/.test(item.desc) ? item.desc : '已智能替换为室内安排（本地兜底）',
          cost: Math.min(item.cost || 50, 60),
        }
      }
      return item
    })
    newDay.highlights = ['室内展馆替代', '露天活动减少', '已在本地模拟调整']
  } else if (action === 'reduce_walking') {
    // 减少步行：合并相邻项，降低步行量
    newDay.items = newDay.items.filter((item, idx) => {
      if (item.tag === '城市漫游' || item.tag === '城市休闲') return false
      if (idx > 0 && idx < newDay.items.length - 1 && idx % 3 === 0) return false
      return true
    })
    // 调整被删除项的前后衔接
    newDay.walking = `${Math.round((parseWalkingDistance(originalDay.walking || '6') * 0.6) / 100) / 10} 公里`
    newDay.cost = newDay.items.reduce((s, it) => s + (it.cost || 0), 0)
    newDay.highlights = ['步行量已降低', '强度已优化', '已在本地模拟调整']
  } else if (action === 'replace_attraction') {
    // 替换景点 —— 匹配所有景点类型标签，智能推导替换名
    const attractionTags = ['近代建筑', '城市地标', '名人故居', '街区文化', '传统街区',
      '民俗文化', '博物馆', '建筑打卡', '夜景', '海边风光', '城市公园', '传统文化',
      '校园周边', '文化场馆', '展馆']
    // 从用户输入提取关键词：如"不喜欢逛博物馆"→"博物馆"
    const dislikeMatch = text.match(/不喜欢|不想|不要|别|讨厌|换掉|换成|替换/)
    const targetKeyword = dislikeMatch ? text.split(/不喜欢|不想|不要|别|讨厌|换掉|换成|替换/)[1]?.trim() : ''
    newDay.items = newDay.items.map((item) => {
      if (attractionTags.includes(item.tag)) {
        // 根据用户关键词或标签推导替换目标
        let newTitle = '替换景点'
        const t = item.title
        if (t.includes('五大') || t.includes('民园')) newTitle = '天津文化中心（美术馆+图书馆）'
        else if (t.includes('瓷房子')) newTitle = '天津自然博物馆'
        else if (t.includes('张学良') || t.includes('故居')) newTitle = '梁启超故居（室内）'
        else if (t.includes('意式') || t.includes('风情')) newTitle = '解放北路金融街漫步'
        else if (t.includes('海河') || t.includes('夜景') || t.includes('天津之眼')) newTitle = '津湾广场+解放桥夜景'
        else if (t.includes('博物') && targetKeyword?.includes('博物')) newTitle = '天津美术馆'
        else if (t.includes('古文化') || t.includes('天后')) newTitle = '鼓楼+广东会馆'
        else if (t.includes('图书馆') || t.includes('滨海')) newTitle = '国家海洋博物馆（室内）'
        else if (t.includes('东疆') || t.includes('海边')) newTitle = '滨海文化中心'
        else newTitle = `天津之眼（${t.slice(0, 4)}替代）`
        return {
          ...item,
          title: newTitle,
          tag: '文化场馆',
          desc: `已根据「${text}」替换（本地兜底）`,
          cost: Math.min(item.cost || 30, 60),
        }
      }
      return item
    })
    newDay.cost = newDay.items.reduce((s, it) => s + (it.cost || 0), 0)
    newDay.highlights = ['资源已替换', '行程已更新', '已在本地模拟调整']
  } else {
    // 通用调整：标记已修改
    newDay.items = newDay.items.map((item, idx) => {
      if (idx > 0 && idx < newDay.items.length - 1 && item.cost > 0) {
        return { ...item, desc: (item.desc || '') + '（已调整）' }
      }
      return item
    })
    newDay.highlights = ['已根据要求调整', '已在本地模拟调整']
  }

  // 根据修改后的 items 重新计算日期大标题
  newDay.title = buildGeneratedDayTitle(newDay.items, targetDay)

  // 更新到响应式状态
  const newDays = [...itineraryDays.value]
  newDays[dayIndex] = newDay
  itineraryDays.value = newDays
  syncBudgetFromItineraryDays()

  appliedAdjustment.value = `已应用智能调整建议：已根据「${action}」修改第 ${targetDay} 天行程（本地模拟）。`
  messages.value.push({
    role: 'assistant',
    text: `已调整第 ${targetDay} 天行程：${text}\n（当前后端未连接，使用本地模拟调整）`,
  })
}

function mapTagToItemType(tag) {
  if (!tag) return 'attraction'
  if (tag === '餐饮') return 'lunch'
  if (tag === '出发准备' || tag === '返程' || tag === '跨区交通') return 'transport'
  if (tag === '城市漫游' || tag === '城市休闲' || tag === '休整') return 'rest'
  return 'attraction'
}

async function loadKnowledgeDocuments() {
  libraryLoading.value = true
  try {
    documents.value = await fetchKnowledgeDocuments(KNOWLEDGE_BASE_ID)
    uploadHint.value = documents.value.length
      ? `已连接 LangChain_RAG：${documents.value.length} 个文档可用于问答`
      : 'LangChain_RAG 当前知识库为空，可上传 PDF、DOCX、TXT、Markdown'
  } catch (error) {
    uploadHint.value = `资料库接口暂不可用：${error.message}`
  } finally {
    libraryLoading.value = false
  }
}

function openUpload() {
  if (uploadingDocuments.value) return
  uploadInput.value?.click()
}

async function handleUpload(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) return

  uploadingDocuments.value = true
  const pendingDocs = files.map((file, index) => ({
    document_id: `pending_${Date.now()}_${index}`,
    name: file.name,
    type: file.name.split('.').pop()?.toUpperCase() || 'FILE',
    size: formatFileSize(file.size),
    status: '写入 Chroma 中',
    chunks: 0
  }))
  documents.value = [...pendingDocs, ...documents.value]
  uploadHint.value = `正在通过 LangChain_RAG 解析 ${files.length} 个文件...`

  let successCount = 0
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index]
    const pendingId = pendingDocs[index].document_id
    try {
      const savedDoc = await uploadKnowledgeDocument(file, KNOWLEDGE_BASE_ID)
      successCount += 1
      documents.value = documents.value.map((doc) => (
        doc.document_id === pendingId ? savedDoc : doc
      ))
    } catch (error) {
      documents.value = documents.value.map((doc) => (
        doc.document_id === pendingId
          ? { ...doc, status: `入库失败：${error.message}` }
          : doc
      ))
    }
  }

  const failedDocs = documents.value.filter((doc) => doc.status?.startsWith('入库失败'))
  if (successCount) {
    await loadKnowledgeDocuments()
    documents.value = [...failedDocs, ...documents.value]
  }
  uploadHint.value = successCount === files.length
    ? `已写入 Chroma ${successCount} 个文件`
    : `已写入 Chroma ${successCount} 个文件，${files.length - successCount} 个失败`
  uploadingDocuments.value = false
}

function formatFileSize(size) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function submitAuth() {
  authError.value = ''
  const username = authForm.value.username.trim()
  const password = authForm.value.password.trim()
  const nickname = authForm.value.nickname.trim()
  if (!username || !password) {
    authError.value = '请输入账号和密码'
    return
  }

  try {
    const user = authMode.value === 'login'
      ? await loginAccount(username, password)
      : await registerAccount(username, password, nickname)
    currentUser.value = user
  } catch (error) {
    currentUser.value = {
      user_id: `local_${username}`,
      username,
      nickname: nickname || username,
      token: 'local-demo-token'
    }
  } finally {
    isAuthenticated.value = true
    authOpen.value = false
  }
}
</script>

<template>
  <section v-if="!isAuthenticated" class="auth-gate">
    <section class="auth-dialog auth-gate-card">
      <div class="auth-copy">
        <p class="eyebrow">Tianjin Travel Planner</p>
        <h1>行知旅策</h1>
        <p>登录后规划、保存和继续调整你的天津自由行。</p>
        <ul>
          <li>保存历史行程和预算记录</li>
          <li>管理天津旅游资料库</li>
          <li>继续追问景点、路线和餐饮建议</li>
        </ul>
      </div>

      <div class="auth-form">
        <div class="auth-tabs">
          <button :class="{ active: authMode === 'login' }" @click="authMode = 'login'">登录</button>
          <button :class="{ active: authMode === 'register' }" @click="authMode = 'register'">注册</button>
        </div>
        <label>
          账号
          <input v-model="authForm.username" placeholder="请输入账号" />
        </label>
        <label>
          密码
          <input v-model="authForm.password" type="password" placeholder="请输入密码" />
        </label>
        <label v-if="authMode === 'register'">
          昵称
          <input v-model="authForm.nickname" placeholder="天津旅行者" />
        </label>
        <button class="primary auth-submit" @click="submitAuth">{{ authMode === 'login' ? '登录进入' : '注册并进入' }}</button>
        <em v-if="authError" class="auth-error">{{ authError }}</em>
        <p>当前为前端演示，后续可接入真实用户接口。</p>
      </div>
    </section>
  </section>

  <div v-else class="app-shell" :class="{ 'qa-shell-mode': activePage === 'qa' }">
    <aside class="sidebar">
      <div class="brand">
        <span>行</span>
        <div>
          <strong>行知旅策</strong>
          <small>智能自由行助手</small>
        </div>
      </div>

      <nav class="nav">
        <button
          v-for="page in pages"
          :key="page.id"
          :class="{ active: activePage === page.id }"
          @click="activePage = page.id"
        >
          {{ page.label }}
        </button>
      </nav>

      <section class="mini-plan">
        <span>当前计划</span>
        <strong v-if="hasPlan">{{ requirements.city || '天津' }} {{ requirements.days || itineraryDays.length }} 日游</strong>
        <strong v-else>还没有行程</strong>
        <p>{{ hasPlan ? (requirements.interests?.join('、') || '已生成规划') : '先说出你的天津旅行想法' }}</p>
      </section>

      <button class="account-entry" @click="authOpen = true">
        <span>{{ currentUser?.nickname || currentUser?.username || '已登录' }}</span>
        <strong>账号中心</strong>
      </button>
    </aside>

    <main class="main">
      <section v-if="activePage === 'plan'" class="page plan-page">
        <div class="hero">
          <div class="hero-content">
            <p class="eyebrow">AI Travel Planner</p>
            <h1>今天想去哪里？</h1>
            <p class="hero-desc">
              输入城市、天数、预算和偏好，我会帮你安排景点、餐厅、路线和预算。
            </p>
            <div class="search-box">
              <textarea v-model="prompt" placeholder="例如：帮我规划天津两日游，预算1800元，喜欢近代建筑和海河夜景，步行不要超过7公里。" @keydown.ctrl.enter="sendPrompt('trip')"></textarea>
              <button
                class="voice-button"
                :class="{ recording: voiceRecording && voiceScene === 'plan' }"
                :disabled="planning && !(voiceRecording && voiceScene === 'plan')"
                @click="toggleVoiceInput('plan')"
              >
                {{ voiceRecording && voiceScene === 'plan' ? '停止' : '语音' }}
              </button>
              <button :disabled="planning" @click="sendPrompt('trip')">{{ planning ? '规划中' : '生成行程' }}</button>
            </div>
            <p v-if="voiceRecording && voiceScene === 'plan'" class="voice-status">正在录音，说完后点“停止”。</p>
            <p v-else-if="voiceError" class="voice-status error">{{ voiceError }}</p>
            <div class="quick-prompts">
              <button @click="fillPrompt('帮我规划天津两日游，预算1800元，喜欢近代建筑和海河夜景。')">天津经典两日</button>
              <button @click="fillPrompt('把第二天下午改成室内景点，并减少步行。')">减少步行</button>
              <button @click="fillPrompt('五大道有哪些游览注意事项？请给出来源。', 'qa')">问五大道注意事项</button>
            </div>
          </div>

          <div class="hero-card">
            <img src="https://images.unsplash.com/photo-1518156677180-95a2893f3e9f?auto=format&fit=crop&w=900&q=80" alt="天津城市旅行" />
            <div class="hero-card-body">
              <span>{{ hasPlan ? '当前方案' : '示例灵感' }}</span>
              <strong>{{ hasPlan ? `${requirements.city || '天津'}${requirements.days || itineraryDays.length}日自由行` : '天津海河建筑路线' }}</strong>
              <p>{{ hasPlan ? (requirements.interests?.join(' · ') || '已生成行程') : '五大道 · 意风区 · 海河' }}</p>
            </div>
            <div class="hero-route-card">
              <span>{{ hasPlan ? '步行距离' : '生成后展示' }}</span>
              <strong>{{ hasPlan ? activeItinerary.walking : '步行 / 预算' }}</strong>
              <p>{{ hasPlan ? '仅统计步行路段' : '会在规划后自动汇总' }}</p>
            </div>
          </div>
        </div>

        <div v-if="hasPlan" class="summary-grid">
          <article v-for="item in preferenceSummary" :key="item.label" class="summary-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </article>
        </div>
        <div v-else class="summary-grid starter-grid">
          <article class="summary-card">
            <span>第一步</span>
            <strong>说出天数和预算</strong>
          </article>
          <article class="summary-card">
            <span>第二步</span>
            <strong>补充兴趣偏好</strong>
          </article>
          <article class="summary-card">
            <span>第三步</span>
            <strong>生成后继续修改</strong>
          </article>
        </div>

        <section v-if="hasPlan || planning" class="panel progress-panel">
          <div class="section-title">
            <h2>规划进度</h2>
            <p>系统会先理解需求，再安排地点、路线和预算。</p>
          </div>
          <div class="progress-steps">
            <article v-for="(item, index) in planningProgress" :key="item.title" :class="['progress-step', item.status]">
              <span>{{ index + 1 }}</span>
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.desc }}</p>
              </div>
            </article>
          </div>
        </section>
      </section>

      <section v-else-if="activePage === 'trip'" class="page trip-page">
        <template v-if="hasPlan">
        <div class="page-head">
          <div>
            <p class="eyebrow">Your Itinerary</p>
            <h1>{{ requirements.city || '天津' }} {{ requirements.days || itineraryDays.length }} 日自由行</h1>
            <p>按兴趣偏好、预算和步行强度生成，支持继续对话修改某一天或某个时段。</p>
          </div>
        </div>

        <section class="trip-overview">
          <article>
            <span>住宿锚点</span>
            <strong>{{ activeItinerary.hotel }}</strong>
            <p>每日从酒店出发并返回，减少路线折返。</p>
          </article>
          <article>
            <span>当日区域</span>
            <strong>{{ activeItinerary.area }}</strong>
            <p>相邻景点聚合安排，避免跨城奔波。</p>
          </article>
          <article>
            <span>交通耗时</span>
            <strong>{{ activeItinerary.routeTime }}</strong>
            <p>已预留地点间交通时间。</p>
          </article>
          <article>
            <span>校验结果</span>
            <strong>通过</strong>
            <p>预算、步行和时间安排均合理。</p>
          </article>
        </section>

        <div class="day-tabs">
          <button v-for="day in itineraryDays" :key="day.day" :class="{ active: activeDay === day.day }" @click="activeDay = day.day">
            第 {{ day.day }} 天
          </button>
        </div>

        <section class="panel smart-adjust-panel">
          <div class="smart-adjust-head">
            <div>
              <p class="eyebrow">Smart Adjustment</p>
              <h2>智能修改行程</h2>
              <span>告诉系统天气、体力、预算或偏好变化，它会自动判断影响哪些安排。</span>
            </div>
            <button class="submit-edit" @click="analyzeSmartAdjustment">生成调整建议</button>
          </div>
          <textarea v-model="smartAdjustInput" placeholder="例如：今天下午下雨了，帮我把露天景点改成室内安排" @input="clearSmartAdjustmentResult"></textarea>
          <div v-if="smartAdjustPreview" class="adjust-preview natural-adjust-preview">
            <div class="adjust-impact">
              <span>影响范围</span>
              <strong>{{ smartAdjustPreview.scope || '当前行程' }}</strong>
              <p>{{ smartAdjustPreview.summary || '系统已生成修改建议，确认后再替换当前行程。' }}</p>
            </div>
            <div class="adjust-action-zone">
              <div class="adjust-change-list" :class="{ empty: !smartAdjustPreview.changes.length }">
                <article v-for="change in smartAdjustPreview.changes.slice(0, 3)" :key="`${change.from}-${change.to}`">
                  <span>{{ change.label || '调整' }}</span>
                  <strong>{{ change.from }}</strong>
                  <p>改为：{{ change.to }}</p>
                  <small>{{ change.why }}</small>
                </article>
                <p v-if="!smartAdjustPreview.changes.length" class="adjust-empty-tip">没有生成可直接应用的修改，请再补充一天、地点或预算要求。</p>
              </div>
              <button
                v-if="smartAdjustPreview.ready !== false"
                class="submit-edit apply-adjust-btn"
                :disabled="applyingAdjustment"
                @click="applySmartAdjustment"
              >{{ applyingAdjustment ? '应用中' : '应用这些修改' }}</button>
            </div>
          </div>
          <p v-if="appliedAdjustment" class="adjust-status">{{ appliedAdjustment }}</p>
        </section>

        <section class="itinerary-layout">
          <div class="panel itinerary-panel">
            <div class="itinerary-head">
              <div>
                <h2>{{ activeItinerary.title }}</h2>
                <p>{{ activeItinerary.walking }} · 预计 {{ activeItinerary.cost }} 元 · {{ activeItinerary.date }}</p>
              </div>
              <span class="pass-badge">强度适中</span>
            </div>
            <div class="timeline">
              <article v-for="item in activeItinerary.items" :key="`${activeItinerary.day}-${item.time}`">
                <time>{{ item.time }}</time>
                <i></i>
                <div>
                  <span>{{ item.tag }}</span>
                  <strong class="place-link" @click="openPlaceDetail(item)">{{ item.title }}</strong>
                  <p>{{ item.desc }}</p>
                  <footer>
                    <small>{{ item.route }}</small>
                    <em>{{ item.cost }} 元</em>
                  </footer>
                </div>
              </article>
            </div>
          </div>

          <aside class="trip-side">
            <section class="panel day-summary">
              <h3>当日摘要</h3>
              <div class="summary-row">
                <span>步行</span>
                <strong>{{ activeItinerary.walking }}</strong>
              </div>
              <div class="summary-row">
                <span>费用</span>
                <strong>{{ activeItinerary.cost }} 元</strong>
              </div>
              <div class="summary-row">
                <span>日程</span>
                <strong>{{ activeItinerary.items.length }} 个安排</strong>
              </div>
            </section>

            <section class="panel reason-card">
              <h3>推荐依据</h3>
              <ul>
                <li v-for="item in activeItinerary.highlights" :key="item">{{ item }}</li>
              </ul>
            </section>


            <section class="panel backup-card">
              <h3>备选安排</h3>
              <button @click="smartAdjustInput = `把第 ${activeItinerary.day} 天改得更轻松，减少步行`">
                <span>低步行替代</span>
                <strong>减少室外连续步行</strong>
              </button>
              <button @click="smartAdjustInput = `第 ${activeItinerary.day} 天如果下雨，帮我替换成室内景点`">
                <span>雨天方案</span>
                <strong>改成展馆 / 商圈休息</strong>
              </button>
              <button @click="smartAdjustInput = `把第 ${activeItinerary.day} 天晚上的安排提前结束`">
                <span>提前返程</span>
                <strong>压缩夜间行程</strong>
              </button>
            </section>

            <section class="panel travel-note-card">
              <h3>出行提醒</h3>
              <article>
                <span>弹性时间</span>
                <p>每两个景点之间建议保留 10-15 分钟缓冲，方便拍照、补水和临时排队。</p>
              </article>
              <article>
                <span>资料状态</span>
                <p>{{ itinerarySourceText }}</p>
              </article>
            </section>

          </aside>
        </section>
        </template>
        <section v-else class="empty-state">
          <p class="eyebrow">No Itinerary</p>
          <h1>还没有生成行程</h1>
          <p>先在智能规划里告诉我天数、预算、同行人和偏好，生成后这里会展示每天的时间线、地点详情和智能修改入口。</p>
          <button class="primary" @click="activePage = 'plan'">去生成行程</button>
        </section>
      </section>

      <section v-else-if="activePage === 'map'" class="page map-page">
        <div class="page-head">
          <div>
            <p class="eyebrow">Route Map</p>
            <h1>路线地图</h1>
            <p>{{ hasPlan ? '展示推荐地点、坐标状态和地点卡片，点击 Marker 或卡片可同步定位。' : '当前显示演示推荐地点，生成行程后会替换为真实推荐资源。' }}</p>
          </div>
          <button class="primary" :disabled="mapLoading" @click="loadMapResources">{{ mapLoading ? '加载中' : '刷新地图资源' }}</button>
        </div>
        <TripMap
          :session-id="sessionId || 'demo_session'"
          :resources="mapResources"
          :routes="recommendedRoutes"
          :itinerary-days="itineraryDays"
          :active-day="activeDay"
          :loading="mapLoading"
          :error="mapError"
          @change-day="activeDay = $event"
          @retry="loadMapResources"
        />
      </section>

      <section v-else-if="activePage === 'budget'" class="page budget-page">
        <template v-if="hasPlan">
        <div class="page-head">
          <div>
            <p class="eyebrow">Budget</p>
            <h1>预算概览</h1>
            <p>预计花费 {{ totalSpent }} 元，剩余 {{ remainingBudget }} 元。</p>
          </div>
        </div>
        <BudgetPanel
          :budget="{
            hotel_cost: budget.find(b => b.label === '酒店')?.value || 0,
            ticket_cost: budget.find(b => b.label === '门票')?.value || 0,
            meal_cost: budget.find(b => b.label === '餐饮')?.value || 0,
            transport_cost: budget.find(b => b.label === '交通')?.value || 0,
            other_cost: 0,
            total_cost: totalSpent,
            total_budget: requirements.total_budget || 0,
            remaining_budget: remainingBudget,
            over_budget: remainingBudget < 0,
          }"
        />
        </template>
        <section v-else class="empty-state">
          <p class="eyebrow">Budget</p>
          <h1>暂无预算</h1>
          <p>等行程生成后，系统会把酒店、餐饮、门票和交通费用拆开显示。</p>
          <button class="primary" @click="activePage = 'plan'">先去规划</button>
        </section>
      </section>

      <section v-else-if="activePage === 'qa'" class="page qa-page">
        <section class="qa-chat-shell">
          <section class="chatgpt-layout">
            <header class="chat-header">
              <div>
                <p class="eyebrow">Travel Q&A</p>
                <h1>天津旅行问答</h1>
                <span>{{ documents.length }} 份资料可参考，回答会尽量给出来源。</span>
              </div>
              <button class="ghost-button" @click="activePage = 'library'">上传资料</button>
            </header>

            <div class="chat-suggestions">
              <button v-for="item in qaSuggestions" :key="item" @click="fillPrompt(item, 'qa')">{{ item }}</button>
            </div>

            <div class="chat-thread">
              <article v-for="(message, index) in messages" :key="index" class="chat-row" :class="message.role">
                <div class="avatar">{{ message.role === 'user' ? '你' : 'AI' }}</div>
                <div class="message-content">
                  <button
                    v-if="message.audioUrl"
                    class="voice-bubble"
                    :class="{ playing: playingVoiceUrl === message.audioUrl }"
                    @click="toggleVoicePlayback($event, message.audioUrl)"
                  >
                    <span class="voice-bubble__icon"></span>
                    <span class="voice-bubble__waves"><i></i><i></i><i></i></span>
                    <span class="voice-bubble__label">语音提问</span>
                    <span class="voice-bubble__time">{{ playingVoiceUrl === message.audioUrl ? '播放中' : '' }}</span>
                    <audio
                      :src="message.audioUrl"
                      :type="message.audioType || 'audio/webm'"
                      preload="metadata"
                      data-voice-player="true"
                      @ended="stopVoicePlayback(message.audioUrl)"
                      @pause="stopVoicePlayback(message.audioUrl)"
                    ></audio>
                  </button>
                  <div v-else-if="message.isStreaming && !message.text" class="typing-loader">
                    <i></i><i></i><i></i>
                  </div>
                  <div v-else v-html="formatMessage(message.text)"></div>
                </div>
              </article>
            </div>

            <div class="chat-composer">
              <textarea v-model="prompt" placeholder="问问天津旅行，比如：五大道下午去会不会太赶？" @keydown.ctrl.enter="sendPrompt('qa')"></textarea>
              <button
                class="voice-button"
                :class="{ recording: voiceRecording && voiceScene === 'qa' }"
                :disabled="planning && !(voiceRecording && voiceScene === 'qa')"
                @click="toggleVoiceInput('qa')"
              >
                {{ voiceRecording && voiceScene === 'qa' ? '停止' : '语音' }}
              </button>
              <button :disabled="planning" @click="sendPrompt('qa')">{{ planning ? '查询中' : '发送' }}</button>
            </div>
            <p v-if="voiceRecording && voiceScene === 'qa'" class="voice-status">正在录音，说完后点“停止”。</p>
            <p v-else-if="voiceError" class="voice-status error">{{ voiceError }}</p>
          </section>

          <aside class="chat-right-panel">
            <section class="qa-ask-panel">
              <h3>提问</h3>
              <textarea v-model="prompt" placeholder="问问天津旅行，比如：五大道下午去会不会太赶？" @keydown.ctrl.enter="sendPrompt('qa')"></textarea>
              <button @click="sendPrompt('qa')">{{ planning ? '查询中' : '发送' }}</button>
            </section>

            <section>
              <h3>最近旅行</h3>
              <button v-if="!tripHistory.length" @click="activePage = 'plan'">
                <strong>暂无历史行程</strong>
                <span>生成后会保存在这里</span>
              </button>
              <button v-for="item in tripHistory.slice(0, 3)" :key="`qa-history-${item.id}`" @click="activePage = 'history'">
                <strong>{{ item.title }}</strong>
                <span>{{ item.date }} · {{ item.status }}</span>
              </button>
            </section>

            <section>
              <h3>当前资料</h3>
              <button v-for="doc in documents.slice(0, 3)" :key="`qa-doc-${doc.name}`" @click="activePage = 'library'">
                <strong>{{ doc.name }}</strong>
                <span>{{ doc.chunks }} 个片段 · {{ doc.status }}</span>
              </button>
            </section>
          </aside>
        </section>
      </section>

      <section v-else-if="activePage === 'history'" class="page history-page">
        <div class="page-head">
          <div>
            <p class="eyebrow">Travel History</p>
            <h1>旅行历史</h1>
            <p>查看之前生成或保存过的天津旅行方案，后续可以接入真实账号数据。</p>
          </div>
          <button class="primary" @click="activePage = 'plan'">新建规划</button>
        </div>

        <section v-if="tripHistory.length" class="history-list">
          <article v-for="item in tripHistory" :key="item.id" class="history-card">
            <div>
              <span>{{ item.date }}</span>
              <strong>{{ item.title }}</strong>
              <p>{{ item.tags.join(' · ') }}</p>
            </div>
            <aside>
              <em>{{ item.status }}</em>
              <b>{{ item.budget }} 元</b>
              <button @click="activePage = 'trip'">查看行程</button>
            </aside>
          </article>
        </section>
        <section v-else class="empty-state compact-empty">
          <p class="eyebrow">No History</p>
          <h1>还没有保存过旅行</h1>
          <p>生成天津行程后，可以把方案保存到这里，之后继续查看或二次修改。</p>
          <button class="primary" @click="activePage = 'plan'">新建第一个行程</button>
        </section>
      </section>

      <section v-else class="page library-page">
        <div class="page-head">
          <div>
            <p class="eyebrow">Knowledge Base</p>
            <h1>旅行资料库</h1>
            <p>上传景点攻略、城市资料和注意事项，问答和推荐理由会优先参考这些资料。</p>
          </div>
        </div>

        <section class="upload-panel">
          <input
            ref="uploadInput"
            class="file-input"
            type="file"
            multiple
            accept=".pdf,.doc,.docx,.txt,.md"
            @change="handleUpload"
          />
          <div>
            <span>上传资料</span>
            <strong>把旅游文档拖进知识库</strong>
            <p>{{ uploadHint }}</p>
          </div>
          <button class="primary" :disabled="uploadingDocuments" @click="openUpload">
            {{ uploadingDocuments ? '写入中' : '选择文件' }}
          </button>
        </section>

        <section class="panel docs-panel">
          <div class="section-title">
            <h2>已上传资料</h2>
            <p>{{ libraryLoading ? '正在读取 LangChain_RAG' : `${documents.length} 个文档` }}</p>
          </div>
          <div class="doc-list">
            <article v-for="doc in documents" :key="doc.document_id || doc.name">
              <div>
                <strong>{{ doc.name }}</strong>
                <span>{{ doc.type }} · {{ doc.size }} · {{ doc.chunks }} 个片段</span>
              </div>
              <em>{{ doc.status }}</em>
            </article>
            <article v-if="!libraryLoading && !documents.length">
              <div>
                <strong>暂无入库文档</strong>
                <span>请上传资料，或先在 LangChain_RAG 中完成文档入库。</span>
              </div>
              <em>等待资料</em>
            </article>
          </div>
        </section>
      </section>
    </main>

    <div v-if="authOpen" class="auth-modal">
      <section class="auth-dialog">
        <button class="modal-close" @click="authOpen = false">×</button>
        <div class="auth-copy">
          <p class="eyebrow">Account</p>
          <h1>账号中心</h1>
          <p>登录后保存你的天津旅行方案、资料库和问答记录。</p>
          <ul>
            <li>同步旅行历史</li>
            <li>保留资料状态</li>
            <li>继续调整方案</li>
          </ul>
        </div>

        <div class="auth-form">
          <div class="auth-tabs">
            <button :class="{ active: authMode === 'login' }" @click="authMode = 'login'">登录</button>
            <button :class="{ active: authMode === 'register' }" @click="authMode = 'register'">注册</button>
          </div>
          <label>
            账号
            <input v-model="authForm.username" placeholder="请输入账号" />
          </label>
          <label>
            密码
            <input v-model="authForm.password" type="password" placeholder="请输入密码" />
          </label>
          <label v-if="authMode === 'register'">
            昵称
            <input v-model="authForm.nickname" placeholder="天津旅行者" />
          </label>
          <button class="primary auth-submit" @click="submitAuth">{{ authMode === 'login' ? '登录' : '创建账号' }}</button>
          <em v-if="authError" class="auth-error">{{ authError }}</em>
          <p>当前为前端演示，后续可接入真实用户接口。</p>
        </div>
      </section>
    </div>

    <div v-if="selectedPlace" class="place-modal">
      <section class="place-dialog">
        <button class="modal-close" @click="selectedPlace = null">×</button>
        <img :src="selectedPlace.image" :alt="selectedPlace.title" />
        <div class="place-dialog-body">
          <p class="eyebrow">Place Detail</p>
          <h2>{{ selectedPlace.title }}</h2>
          <p>{{ selectedPlace.desc }}</p>
          <div class="place-tips">
            <span v-for="tip in selectedPlace.tips" :key="tip">{{ tip }}</span>
          </div>
          <button class="primary" @click="selectedPlace = null">知道了</button>
        </div>
      </section>
    </div>
  </div>
</template>

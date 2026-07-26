<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import TripMap from './components/TripMap.vue'
import {
  createSession,
  fetchMapResourcesByPlaceIds,
  getMockMapResources,
  healthCheck,
  loginAccount,
  registerAccount,
  sendMessage,
  streamMessage
} from './api'

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
const sessionId = ref('')
const apiError = ref('')
const hasPlan = ref(false)
const STORAGE_KEY = 'voyage-mind-member1-state'

const messages = ref([])

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
const selectedEditItem = ref(null)
const editRequest = ref('')
const smartAdjustInput = ref('')
const smartAdjustPreview = ref(null)
const appliedAdjustment = ref('')
const selectedPlace = ref(null)
const recommendationResult = ref(null)
const currentItineraryPayload = ref(null)
const recommendedRoutes = ref([])
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
    image: 'https://images.unsplash.com/photo-1518156677180-95a2893f3e9f?auto=format&fit=crop&w=900&q=80',
    title: '五大道文化旅游区',
    desc: '天津近代建筑最集中的街区之一，适合慢行、拍照和了解租界时期建筑风格。',
    tips: ['建议上午游览', '民园广场可作为起点', '步行时间建议控制在 2 小时左右']
  },
  民园广场休息拍照: {
    image: 'https://images.unsplash.com/photo-1518005020951-eccb494ad742?auto=format&fit=crop&w=900&q=80',
    title: '民园广场',
    desc: '五大道核心休息点，适合拍照、补水和调整游览节奏。',
    tips: ['适合短暂停留', '周边咖啡店较多', '可衔接五大道建筑群']
  },
  瓷房子外观: {
    image: 'https://images.unsplash.com/photo-1518005020951-eccb494ad742?auto=format&fit=crop&w=900&q=80',
    title: '瓷房子',
    desc: '天津市区标志性建筑之一，外观辨识度高，可根据预算选择是否入内。',
    tips: ['可只看外观', '雨天可缩短停留', '周边适合街区漫游']
  },
  张学良故居: {
    image: 'https://images.unsplash.com/photo-1518005020951-eccb494ad742?auto=format&fit=crop&w=900&q=80',
    title: '张学良故居',
    desc: '近代历史相关景点，适合补充人物故事和天津城市历史内容。',
    tips: ['室内外结合', '适合低强度游览', '建议预留 40-60 分钟']
  },
  意式风情区: {
    image: 'https://images.unsplash.com/photo-1518005020951-eccb494ad742?auto=format&fit=crop&w=900&q=80',
    title: '意式风情区',
    desc: '以欧式建筑、餐饮和街区氛围为主，适合傍晚散步和晚餐。',
    tips: ['傍晚体验更好', '餐厅选择多', '雨天可缩短露天停留']
  },
  海河夜景与天津之眼外观: {
    image: 'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80',
    title: '海河夜景与天津之眼',
    desc: '天津夜游核心体验，可选择步行、车览、游船或摩天轮外观打卡。',
    tips: ['晚间灯光更好', '雨天建议车览', '注意返程交通时间']
  },
  天津博物馆: {
    image: 'https://images.unsplash.com/photo-1566127444979-b3d2b654e3d7?auto=format&fit=crop&w=900&q=80',
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

const documents = ref([
  { name: '五大道游览资料.pdf', type: 'PDF', size: '1.6 MB', status: '可用于问答', chunks: 44 },
  { name: '天津博物馆资料.md', type: 'Markdown', size: '74 KB', status: '可用于问答', chunks: 28 },
  { name: '天津餐饮文化.txt', type: 'TXT', size: '39 KB', status: '可用于问答', chunks: 19 }
])

const uploadInput = ref(null)
const uploadHint = ref('支持 PDF、DOCX、TXT、Markdown 旅游资料')
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
  const ids = recommendationPlaces(recommendationResult.value)
    .map((place) => place.place_id)
    .filter(Boolean)
  return ids.length ? ids : fallbackMapPlaceIds
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
  loadMapResources()
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

watch(
  [
    activePage,
    sessionId,
    hasPlan,
    messages,
    requirements,
    itineraryDays,
    activeDay,
    tripHistory,
    documents,
    currentUser,
    isAuthenticated,
    recommendationResult,
    currentItineraryPayload,
    recommendedRoutes,
    mapResources,
    budget
  ],
  persistState,
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
    documents: documents.value,
    currentUser: currentUser.value,
    isAuthenticated: isAuthenticated.value,
    recommendationResult: recommendationResult.value,
    currentItineraryPayload: currentItineraryPayload.value,
    recommendedRoutes: recommendedRoutes.value,
    mapResources: mapResources.value,
    budget: budget.value
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
  messages.value = Array.isArray(payload.messages) ? payload.messages : []
  requirements.value = payload.requirements && typeof payload.requirements === 'object'
    ? { ...requirements.value, ...payload.requirements }
    : requirements.value
  itineraryDays.value = Array.isArray(payload.itineraryDays) && payload.itineraryDays.length
    ? payload.itineraryDays
    : itineraryDays.value
  activeDay.value = Number(payload.activeDay) || 1
  tripHistory.value = Array.isArray(payload.tripHistory) ? payload.tripHistory : []
  documents.value = Array.isArray(payload.documents) ? payload.documents : documents.value
  currentUser.value = payload.currentUser || null
  isAuthenticated.value = Boolean(payload.isAuthenticated && payload.currentUser)
  recommendationResult.value = payload.recommendationResult || null
  currentItineraryPayload.value = payload.currentItineraryPayload || null
  recommendedRoutes.value = Array.isArray(payload.recommendedRoutes) ? payload.recommendedRoutes : []
  mapResources.value = Array.isArray(payload.mapResources) && payload.mapResources.length
    ? payload.mapResources
    : mapResources.value
  budget.value = Array.isArray(payload.budget) && payload.budget.length ? payload.budget : budget.value
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

  messages.value.push({ role: 'user', text })
  prompt.value = ''
  planning.value = true
  planningProgress.value = planningProgress.value.map((item, index) => ({
    ...item,
    status: index === 0 ? 'active' : 'pending'
  }))

  try {
    if (targetPage === 'qa') {
      const assistantIndex = messages.value.push({ role: 'assistant', text: '' }) - 1
      await streamMessage(sessionId.value || `local_${Date.now()}`, text, (_chunk, fullText) => {
        messages.value[assistantIndex].text = fullText
      })
    } else {
      const response = await sendMessage(sessionId.value || `local_${Date.now()}`, text)
      messages.value.push({ role: 'assistant', text: response.reply })
      requirements.value = response.requirements || requirements.value
      applyRecommendationPayload(response)
      applyItineraryPayload(response, text)
      hasPlan.value = true
      saveCurrentTripHistory()
    }
    planningProgress.value = [
      { title: '理解你的需求', desc: '已识别目的地、天数、预算和兴趣偏好', status: 'done' },
      { title: '筛选推荐地点', desc: recommendationResult.value ? '已调用旅游资源推荐模块并返回地点结果' : '已准备调用景点、餐厅和住宿推荐', status: 'done' },
      { title: '安排每日路线', desc: routeProgressText(), status: 'active' },
      { title: '检查预算与强度', desc: '预算、步行和开放时间会在生成后校验', status: 'pending' }
    ]
    activePage.value = targetPage
  } catch (error) {
    apiError.value = error.message
    messages.value.push({
      role: 'assistant',
      text: '我先按演示数据生成一份天津两日游方案。后端连接后，会自动替换为真实规划结果。'
    })
    if (targetPage !== 'qa') {
      syncItineraryDays(text)
      hasPlan.value = true
      saveCurrentTripHistory()
    }
    planningProgress.value = planningProgress.value.map((item) => ({ ...item, status: 'done' }))
    activePage.value = targetPage
  } finally {
    planning.value = false
  }
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
    syncBudgetFromGeneratedItinerary(currentItineraryPayload.value)
    return
  }
  syncItineraryDays(fallbackText)
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
    time: item.start_time || '待定',
    title,
    tag: typeLabel,
    desc,
    cost: Math.round(Number(item.total_cost ?? item.cost_per_person) || 0),
    route,
    detail: {
      image: generatedPlaceImage(item.item_type),
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
  return `${(meters / 1000).toFixed(1)} 公里`
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

function selectEditItem(item) {
  selectedEditItem.value = {
    day: activeItinerary.value.day,
    time: item.time,
    title: item.title,
    tag: item.tag
  }
  editRequest.value = `调整第 ${activeItinerary.value.day} 天 ${item.time} 的「${item.title}」`
}

function openPlaceDetail(item) {
  selectedPlace.value = item.detail || placeDetails[item.title] || {
    image: 'https://images.unsplash.com/photo-1518156677180-95a2893f3e9f?auto=format&fit=crop&w=900&q=80',
    title: item.title,
    desc: item.desc,
    tips: [item.tag, item.route, '可根据天气、体力和预算继续调整']
  }
}

function applyEditPreset(text) {
  const target = selectedEditItem.value
    ? `第 ${selectedEditItem.value.day} 天 ${selectedEditItem.value.time}「${selectedEditItem.value.title}」`
    : `第 ${activeItinerary.value.day} 天`
  editRequest.value = `把${target}${text}`
}

function submitEditRequest() {
  const text = editRequest.value.trim()
  if (!text) return
  appliedAdjustment.value = `已提交修改：${text}`
  messages.value.push({ role: 'user', text })
  messages.value.push({ role: 'assistant', text: '已收到修改要求，我会保持在当前行程页，并优先调整受影响的时间段。' })
}

function analyzeSmartAdjustment() {
  const text = smartAdjustInput.value.trim()
  if (!text) return
  smartAdjustPreview.value = {
    reason: text,
    affected: ['14:00 瓷房子外观', '17:00 意式风情区', '19:00 海河夜景与天津之眼外观'],
    changes: [
      { from: '瓷房子外观', to: '天津博物馆', why: '室内展馆，适合雨天替代' },
      { from: '意式风情区', to: '西岸艺术馆 / 商场休息', why: '减少露天步行和淋雨风险' },
      { from: '海河夜景', to: '海河夜景改为车览或顺延', why: '保留核心体验，但降低天气影响' }
    ]
  }
}

function clearSmartAdjustmentResult() {
  smartAdjustPreview.value = null
  appliedAdjustment.value = ''
}

function applySmartAdjustment() {
  if (!smartAdjustPreview.value) return
  const text = `根据情况自动调整行程：${smartAdjustPreview.value.reason}。受影响安排：${smartAdjustPreview.value.affected.join('、')}。请替换为室内或低步行方案。`
  appliedAdjustment.value = '已应用智能调整建议：露天安排将优先替换为室内或低步行方案。'
  messages.value.push({ role: 'user', text })
  messages.value.push({ role: 'assistant', text: appliedAdjustment.value })
}

function openUpload() {
  uploadInput.value?.click()
}

function handleUpload(event) {
  const files = Array.from(event.target.files || [])
  if (!files.length) return
  const newDocs = files.map((file) => ({
    name: file.name,
    type: file.name.split('.').pop()?.toUpperCase() || 'FILE',
    size: formatFileSize(file.size),
    status: '处理中',
    chunks: 0
  }))
  documents.value = [...newDocs, ...documents.value]
  uploadHint.value = `已添加 ${files.length} 个文件，等待后端解析入库`
  event.target.value = ''
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
              <button :disabled="planning" @click="sendPrompt('trip')">{{ planning ? '规划中' : '生成行程' }}</button>
            </div>
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
              <span>{{ hasPlan ? '当前路线' : '生成后展示' }}</span>
              <strong>{{ hasPlan ? activeItinerary.walking : '路线 / 预算' }}</strong>
              <p>{{ hasPlan ? '步行 + 地铁 · 强度适中' : '会在规划后自动汇总' }}</p>
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
            <article v-for="item in planningProgress" :key="item.title" :class="['progress-step', item.status]">
              <span></span>
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
          <div v-if="smartAdjustPreview" class="adjust-preview horizontal-preview">
            <div>
              <span>系统识别到会影响</span>
              <p>{{ smartAdjustPreview.affected.join('、') }}</p>
            </div>
            <article v-for="change in smartAdjustPreview.changes" :key="change.from">
              <strong>{{ change.from }} → {{ change.to }}</strong>
              <small>{{ change.why }}</small>
            </article>
            <button class="submit-edit" @click="applySmartAdjustment">应用这些修改</button>
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
                    <div class="timeline-actions">
                      <em>{{ item.cost }} 元</em>
                      <button @click="selectEditItem(item)">调整</button>
                    </div>
                  </footer>
                </div>
              </article>
            </div>
          </div>

          <aside class="trip-side">
            <section class="panel mini-map-card">
              <div class="mini-map-head">
                <strong>当日路线</strong>
                <span>{{ activeItinerary.walking }}</span>
              </div>
              <div class="mini-map">
                <span class="mini-pin start">酒店</span>
                <span class="mini-pin a">{{ routeStops[0] }}</span>
                <span class="mini-pin b">{{ routeStops[1] }}</span>
                <span class="mini-pin c">{{ routeStops[2] }}</span>
                <span class="mini-pin d">{{ routeStops[3] }}</span>
                <i class="mini-route one"></i>
                <i class="mini-route two"></i>
                <i class="mini-route three"></i>
              </div>
            </section>

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

            <section class="panel check-card">
              <h3>行程检查</h3>
              <div>
                <span>开放时间</span>
                <strong>正常</strong>
              </div>
              <div>
                <span>步行上限</span>
                <strong>未超限</strong>
              </div>
              <div>
                <span>预算</span>
                <strong>未超支</strong>
              </div>
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
          :resources="mapResources"
          :routes="recommendedRoutes"
          :loading="mapLoading"
          :error="mapError"
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
        <section class="panel budget-panel">
          <div class="budget-ring">
            <strong>{{ budgetPercent }}%</strong>
            <span>预算使用</span>
          </div>
          <div class="budget-list">
            <article v-for="item in budget" :key="item.label">
              <span :style="{ background: item.color }"></span>
              <div>
                <strong>{{ item.label }}</strong>
                <p>{{ item.value }} 元</p>
              </div>
            </article>
          </div>
        </section>
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
                <div class="message-content" v-html="formatMessage(message.text)"></div>
              </article>
            </div>

            <div class="chat-composer">
              <textarea v-model="prompt" placeholder="问问天津旅行，比如：五大道下午去会不会太赶？" @keydown.ctrl.enter="sendPrompt('qa')"></textarea>
              <button :disabled="planning" @click="sendPrompt('qa')">{{ planning ? '查询中' : '发送' }}</button>
            </div>
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
          <button class="primary" @click="openUpload">选择文件</button>
        </section>

        <section class="panel docs-panel">
          <div class="section-title">
            <h2>已上传资料</h2>
            <p>{{ documents.length }} 个文档</p>
          </div>
          <div class="doc-list">
            <article v-for="doc in documents" :key="doc.name">
              <div>
                <strong>{{ doc.name }}</strong>
                <span>{{ doc.type }} · {{ doc.size }} · {{ doc.chunks }} 个片段</span>
              </div>
              <em>{{ doc.status }}</em>
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

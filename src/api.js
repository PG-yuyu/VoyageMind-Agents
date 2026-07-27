const API_BASE = '/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  })
  const payload = await response.json()
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || payload.detail || '请求失败')
  }
  return Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload
}

export function healthCheck() {
  return request('/health')
}

export function createSession(userId = 'demo_user') {
  return request('/sessions', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId })
  })
}

export function loginAccount(username, password) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password })
  })
}

export function registerAccount(username, password, nickname) {
  return request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password, nickname })
  })
}

export function sendMessage(sessionId, message) {
  return request('/chat/messages', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message })
  })
}

export async function streamMessage(sessionId, message, onChunk) {
  const response = await fetch(`${API_BASE}/chat/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ session_id: sessionId, message })
  })
  if (!response.ok || !response.body) {
    throw new Error('流式请求失败')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let fullText = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const chunk = decoder.decode(value, { stream: true })
    fullText += chunk
    onChunk(chunk, fullText)
  }
  return fullText
}

export async function streamGuideChat(payload, onChunk) {
  const response = await fetch(`${API_BASE}/guide/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  })
  if (!response.ok || !response.body) {
    throw new Error('AI 导游请求失败')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let fullText = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const chunk = decoder.decode(value, { stream: true })
    fullText += chunk
    onChunk(chunk, fullText)
  }
  return fullText
}

const MAP_RESOURCE_EXTRAS = {
  place_001: {
    price: 0,
    open_time: '08:30-17:00',
    tags: ['历史文化', '城市地标', '步行友好']
  },
  hotel_001: {
    price: 520,
    open_time: '14:00后入住',
    tags: ['住宿', '交通便利', '和平区']
  },
  restaurant_001: {
    price: 120,
    open_time: '11:00-21:00',
    tags: ['天津菜', '午餐', '本地风味']
  }
}

const MOCK_MAP_RESOURCES = [
  {
    place_id: 'place_001',
    name: '五大道文化旅游区',
    place_type: 'attraction',
    longitude: 117.19937,
    latitude: 39.11787,
    address: '天津市和平区重庆道83号',
    short_description: '天津近代建筑最集中的街区，适合慢行和拍照。',
    recommend_reason: '符合近代建筑和城市漫游偏好，上午游览步行强度可控。',
    verified: true,
    price: 0,
    open_time: '全天开放',
    tags: ['近代建筑', '街区漫游', '拍照']
  },
  {
    place_id: 'hotel_001',
    name: '和平路附近酒店',
    place_type: 'hotel',
    longitude: 117.20669,
    latitude: 39.12942,
    address: '天津市和平区和平路商圈',
    short_description: '靠近地铁和核心商圈，适合作为两日游住宿锚点。',
    recommend_reason: '位于市区核心位置，方便衔接五大道、海河和火车站。',
    verified: true,
    price: 520,
    open_time: '14:00后入住',
    tags: ['住宿', '交通便利', '商圈']
  },
  {
    place_id: 'restaurant_001',
    name: '桂园餐厅天津菜',
    place_type: 'restaurant',
    longitude: 117.19627,
    latitude: 39.11631,
    address: '天津市和平区成都道101号',
    short_description: '经典天津菜餐厅，适合午餐衔接五大道行程。',
    recommend_reason: '餐厅位于五大道附近，能减少午餐前后的折返。',
    verified: true,
    price: 120,
    open_time: '11:00-21:00',
    tags: ['天津菜', '午餐', '本地风味']
  },
  {
    place_id: 'place_missing_coordinate',
    name: '瓷房子坐标待确认',
    place_type: 'attraction',
    longitude: null,
    latitude: null,
    address: '天津市和平区赤峰道72号',
    short_description: '地点信息存在，但当前缺少可用于地图渲染的坐标。',
    recommend_reason: '需要补充坐标后才能作为地图 Marker 展示。',
    verified: false,
    price: 50,
    open_time: '09:00-18:00',
    tags: ['坐标缺失', '待确认']
  },
  {
    place_id: 'place_unverified_001',
    name: '东疆湾海边',
    place_type: 'attraction',
    longitude: 117.79021,
    latitude: 39.02148,
    address: '天津市滨海新区东疆湾',
    short_description: '滨海方向看海地点，距离市区较远。',
    recommend_reason: '坐标未通过地图服务验证，前端需提示用户确认。',
    verified: false,
    price: 80,
    open_time: '以现场为准',
    tags: ['海边风光', '坐标未验证']
  }
]

function normalizeMapResource(resource) {
  const extras = MAP_RESOURCE_EXTRAS[resource.place_id] || {}
  const longitude = Number(resource.longitude)
  const latitude = Number(resource.latitude)
  return {
    ...extras,
    ...resource,
    longitude: Number.isFinite(longitude) ? longitude : null,
    latitude: Number.isFinite(latitude) ? latitude : null,
    verified: resource.verified !== false,
    tags: Array.isArray(resource.tags || extras.tags) ? [...(resource.tags || extras.tags)] : []
  }
}

function normalizeMapPayload(payload) {
  const resources = Array.isArray(payload) ? payload : payload?.resources || []
  return {
    ...payload,
    resources: resources.map(normalizeMapResource)
  }
}

export function getMockMapResources() {
  return MOCK_MAP_RESOURCES.map((resource) => ({
    ...resource,
    tags: [...resource.tags]
  }))
}

export function fetchMapResourcesByPlaceIds(placeIds) {
  return request('/member2/map/resources/by-place-ids', {
    method: 'POST',
    body: JSON.stringify({ place_ids: placeIds })
  }).then(normalizeMapPayload)
}

export function fetchMapResourcesFromRecommendation(result) {
  return request('/member2/map/resources/from-recommendation', {
    method: 'POST',
    body: JSON.stringify(result)
  }).then(normalizeMapPayload)
}

export async function fetchBatchRoutes(routes) {
  const response = await fetch(`${API_BASE}/member2/routes/batch-plan`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ routes })
  })
  const payload = await response.json()
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || payload.detail || '路线接口请求失败')
  }
  return Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload
}

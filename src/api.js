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
  return payload.data
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

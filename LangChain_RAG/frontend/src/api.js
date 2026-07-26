const API_BASE = ''

export async function healthCheck() {
  const response = await fetch(`${API_BASE}/api/health`)
  return readJson(response)
}

export async function listDocuments(knowledgeBaseId) {
  const response = await fetch(`${API_BASE}/api/documents?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`)
  return readJson(response)
}

export async function uploadDocument(file, knowledgeBaseId) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('knowledge_base_id', knowledgeBaseId)

  const response = await fetch(`${API_BASE}/api/documents/ingest`, {
    method: 'POST',
    body: formData
  })
  return readJson(response)
}

export async function deleteDocument(documentId, knowledgeBaseId) {
  const response = await fetch(
    `${API_BASE}/api/documents/${encodeURIComponent(documentId)}?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
    {
      method: 'DELETE'
    }
  )
  return readJson(response)
}

export async function askQuestion(payload) {
  const response = await fetch(`${API_BASE}/api/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  })
  return readJson(response)
}

export async function streamQuestion(payload, onDelta, onSources) {
  const response = await fetch(`${API_BASE}/api/query/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  })

  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail?.message || data.detail || data.message || '请求失败')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      const dataLine = chunk
        .split('\n')
        .find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      const event = JSON.parse(dataLine.slice(5).trim())
      if (event.type === 'delta') {
        onDelta(event.content)
      }
      if (event.type === 'sources') {
        onSources?.(event.sources || [])
      }
      if (event.type === 'error') {
        throw new Error(event.message || '请求失败')
      }
    }
  }
}

async function readJson(response) {
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.detail || data.message || '请求失败')
  }
  return data
}

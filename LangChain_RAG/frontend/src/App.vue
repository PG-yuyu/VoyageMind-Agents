<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { deleteDocument, healthCheck, listDocuments, streamQuestion, uploadDocument } from './api'

const sessionId = `session_${Math.random().toString(16).slice(2, 14)}`

const authMode = ref('login')
const authMessage = ref('')
const currentUser = ref(localStorage.getItem('rag_current_user') || '')
const authForm = ref({
  username: '',
  password: ''
})
const documents = ref([])
const selectedDocumentIds = ref([])
const uploadStatus = ref('点击文件可加入本次 RAG 知识库。')
const fileInput = ref(null)
const health = ref('连接中')
const question = ref('')
const isUploading = ref(false)
const isAsking = ref(false)
const messages = ref([
  {
    role: 'assistant',
    content: '上传并选择左侧文件后，在底部输入问题开始检索问答。',
    sources: [],
    showSources: false
  }
])
const chatAreaEl = ref(null)
const conversations = ref([])
const activeConversationId = ref('')

const selectedCount = computed(() => selectedDocumentIds.value.length)
const isAuthed = computed(() => Boolean(currentUser.value))
const historyKey = computed(() => `rag_conversations_${currentUser.value || 'guest'}`)
const knowledgeBaseId = computed(() => buildUserKnowledgeBaseId(currentUser.value))
const knowledgeBaseLabel = computed(() => `${currentUser.value} 的知识库`)

onMounted(async () => {
  await refreshHealth()
  if (currentUser.value) {
    await refreshDocuments()
    loadConversations()
  }
})

function buildUserKnowledgeBaseId(username) {
  const source = username.trim() || 'guest'
  const encoded = Array.from(source)
    .map((char) => char.charCodeAt(0).toString(16))
    .join('')
  return `kb_member1_${encoded}`
}

async function refreshHealth() {
  try {
    const result = await healthCheck()
    health.value = result.status
  } catch (error) {
    health.value = 'offline'
  }
}

async function refreshDocuments() {
  if (!currentUser.value) {
    documents.value = []
    selectedDocumentIds.value = []
    return
  }

  documents.value = await listDocuments(knowledgeBaseId.value)
  selectedDocumentIds.value = selectedDocumentIds.value.filter((id) =>
    documents.value.some((document) => document.document_id === id)
  )
}

async function onFileChange(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) {
    uploadStatus.value = '请先选择要上传的文件。'
    return
  }

  isUploading.value = true
  uploadStatus.value = '正在上传并处理文档...'
  try {
    for (const file of files) {
      const document = await uploadDocument(file, knowledgeBaseId.value)
      if (!selectedDocumentIds.value.includes(document.document_id)) {
        selectedDocumentIds.value = [...selectedDocumentIds.value, document.document_id]
      }
    }
    uploadStatus.value = '上传成功，点击文件可加入本次 RAG 知识库。'
    await refreshDocuments()
  } catch (error) {
    uploadStatus.value = `上传失败：${error.message}`
  } finally {
    isUploading.value = false
  }
}

function openFilePicker() {
  fileInput.value?.click()
}

function toggleDocument(documentId) {
  if (selectedDocumentIds.value.includes(documentId)) {
    selectedDocumentIds.value = selectedDocumentIds.value.filter((id) => id !== documentId)
  } else {
    selectedDocumentIds.value = [...selectedDocumentIds.value, documentId]
  }
}

function toggleAllDocuments() {
  if (selectedDocumentIds.value.length === documents.value.length) {
    selectedDocumentIds.value = []
  } else {
    selectedDocumentIds.value = documents.value.map((doc) => doc.document_id)
  }
}

async function removeDocument(documentId) {
  const document = documents.value.find((item) => item.document_id === documentId)
  try {
    await deleteDocument(documentId, knowledgeBaseId.value)
    documents.value = documents.value.filter((item) => item.document_id !== documentId)
    selectedDocumentIds.value = selectedDocumentIds.value.filter((id) => id !== documentId)
    uploadStatus.value = document ? `已删除文件：${document.filename}` : '文件已删除。'
  } catch (error) {
    uploadStatus.value = `删除失败：${error.message}`
  }
}

async function sendQuestion() {
  const text = question.value.trim()
  if (!text || isAsking.value) return

  messages.value.push({ role: 'user', content: text })
  const assistantMessage = reactive({
    role: 'assistant',
    content: '',
    isStreaming: true,
    sources: [],
    showSources: false
  })
  const streamDisplay = createSmoothStream(assistantMessage)
  messages.value.push(assistantMessage)
  question.value = ''
  isAsking.value = true
  await nextTick()
  scrollMessagesToBottom()

  try {
    await streamQuestion(
      {
        query: text,
        session_id: sessionId,
        knowledge_base_id: knowledgeBaseId.value,
        selected_document_ids: selectedDocumentIds.value,
        top_k: 10,
        max_hops: 2,
        enable_query_rewrite: true
      },
      (delta) => streamDisplay.enqueue(delta),
      (sources) => {
        assistantMessage.sources = dedupeSources(sources)
      }
    )
    await streamDisplay.finish()
    assistantMessage.isStreaming = false
    saveActiveConversation(text)
  } catch (error) {
    await streamDisplay.finish()
    assistantMessage.content = `请求失败：${error.message}`
    assistantMessage.isStreaming = false
    saveActiveConversation(text)
  } finally {
    isAsking.value = false
    await nextTick()
    scrollMessagesToBottom()
  }
}

function createSmoothStream(message) {
  let queue = ''
  let timer = null
  let resolveFinish = null
  let finishing = false

  const pump = async () => {
    if (!queue) {
      timer = null
      if (finishing && resolveFinish) {
        resolveFinish()
        resolveFinish = null
      }
      return
    }

    const step = Math.min(Math.max(Math.ceil(queue.length / 18), 1), 4)
    message.content += queue.slice(0, step)
    queue = queue.slice(step)
    await nextTick()
    scrollMessagesToBottom()
    timer = window.setTimeout(pump, 16)
  }

  return {
    enqueue(text) {
      queue += text
      if (!timer) {
        pump()
      }
    },
    finish() {
      finishing = true
      if (!queue && !timer) {
        return Promise.resolve()
      }
      return new Promise((resolve) => {
        resolveFinish = resolve
      })
    }
  }
}

function scrollMessagesToBottom() {
  const element = chatAreaEl.value
  if (element) {
    element.scrollTop = element.scrollHeight
  }
}

function renderMarkdown(text, sources = []) {
  const sourceLabels = buildSourceLabels(sources)
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  const lines = escaped.split('\n')
  const html = []
  let listType = ''
  let inCode = false
  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`)
      listType = ''
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    const orderedMatch = line.match(/^\s*(\d+)\.\s+(.+)$/)
    const unorderedMatch = line.match(/^\s*[-*]\s+(.+)$/)

    if (line.trim().startsWith('```')) {
      closeList()
      if (!inCode) {
        html.push('<pre><code>')
        inCode = true
      } else {
        html.push('</code></pre>')
        inCode = false
      }
      continue
    }

    if (inCode) {
      html.push(`${line}\n`)
      continue
    }

    if (orderedMatch || unorderedMatch) {
      const nextType = orderedMatch ? 'ol' : 'ul'
      if (listType && listType !== nextType) {
        closeList()
      }
      if (!listType) {
        const start = orderedMatch ? ` start="${orderedMatch[1]}"` : ''
        html.push(`<${nextType}${start}>`)
        listType = nextType
      }
      html.push(`<li>${formatInlineMarkdown(orderedMatch ? orderedMatch[2] : unorderedMatch[1], sourceLabels)}</li>`)
      continue
    }

    closeList()

    if (!line.trim()) {
      continue
    } else if (/^\s*---+\s*$/.test(line)) {
      html.push('<hr>')
    } else if (line.startsWith('#### ')) {
      html.push(`<h4>${formatInlineMarkdown(line.slice(5), sourceLabels)}</h4>`)
    } else if (line.startsWith('### ')) {
      html.push(`<h3>${formatInlineMarkdown(line.slice(4), sourceLabels)}</h3>`)
    } else if (line.startsWith('## ')) {
      html.push(`<h2>${formatInlineMarkdown(line.slice(3), sourceLabels)}</h2>`)
    } else if (line.startsWith('# ')) {
      html.push(`<h1>${formatInlineMarkdown(line.slice(2), sourceLabels)}</h1>`)
    } else {
      html.push(`<p>${formatInlineMarkdown(line, sourceLabels)}</p>`)
    }
  }

  closeList()
  if (inCode) {
    html.push('</code></pre>')
  }

  return html.join('')
}

function formatInlineMarkdown(text, sourceLabels = {}) {
  const normalized = moveSingleSourceMarkerToEnd(text)

  return normalized
    .replace(/\{\{source:(\d+)\}\}/g, (_, index) => {
      const label = shortenSourceLabel(sourceLabels[index] || '来源')
      return `<span class="inline-source-chip">${label}</span>`
    })
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
}

function handleKeydown(event) {
  if (event.ctrlKey && event.key === 'Enter') {
    sendQuestion()
  }
}

function switchAuthMode(mode) {
  authMode.value = mode
  authMessage.value = ''
}

async function submitAuth() {
  const username = authForm.value.username.trim()
  const password = authForm.value.password.trim()

  if (!username || !password) {
    authMessage.value = '请输入用户名和密码。'
    return
  }

  if (password.length < 6) {
    authMessage.value = '密码长度不能小于 6 位。'
    return
  }

  const users = JSON.parse(localStorage.getItem('rag_users') || '{}')

  if (authMode.value === 'register') {
    if (users[username]) {
      authMessage.value = '该用户名已注册。'
      return
    }
    users[username] = { password }
    localStorage.setItem('rag_users', JSON.stringify(users))
    localStorage.setItem('rag_current_user', username)
    currentUser.value = username
    selectedDocumentIds.value = []
    await refreshDocuments()
    loadConversations()
    authMessage.value = ''
    return
  }

  if (!users[username] || users[username].password !== password) {
    authMessage.value = '用户名或密码错误。'
    return
  }

  localStorage.setItem('rag_current_user', username)
  currentUser.value = username
  selectedDocumentIds.value = []
  await refreshDocuments()
  loadConversations()
  authMessage.value = ''
}

function logout() {
  localStorage.removeItem('rag_current_user')
  currentUser.value = ''
  conversations.value = []
  activeConversationId.value = ''
  documents.value = []
  selectedDocumentIds.value = []
  uploadStatus.value = '点击文件可加入本次 RAG 知识库。'
  authForm.value.password = ''
}

function defaultMessages() {
  return [
    {
      role: 'assistant',
      content: '上传并选择左侧文件后，在底部输入问题开始检索问答。',
      sources: [],
      showSources: false
    }
  ]
}

function moveSingleSourceMarkerToEnd(text) {
  const markers = [...text.matchAll(/\{\{source:\d+\}\}/g)]
  if (!markers.length) return text

  const marker = markers[markers.length - 1][0]
  const cleanText = text
    .replace(/\s*\{\{source:\d+\}\}\s*/g, '')
    .trimEnd()

  if (!cleanText) return marker
  return `${cleanText}${marker}`
}

function shortenSourceLabel(label) {
  if (!label || label === '来源') return '来源'
  const [filename, pageSuffix = ''] = label.split(' · ')
  const dotIndex = filename.lastIndexOf('.')
  const extension = dotIndex > 0 ? filename.slice(dotIndex) : ''
  const name = dotIndex > 0 ? filename.slice(0, dotIndex) : filename
  const maxLength = extension ? 5 : 7
  if (name.length <= maxLength) return label
  const suffix = pageSuffix ? ` · ${pageSuffix}` : ''
  return `${name.slice(0, maxLength)}...${extension}${suffix}`
}

function buildSourceLabels(sources = []) {
  const labels = {}

  sources.forEach((source, index) => {
    const citationIndex = source.citation_index || index + 1
    labels[String(citationIndex)] = source.filename || '来源'
  })

  return labels
}

function loadConversations() {
  conversations.value = JSON.parse(localStorage.getItem(historyKey.value) || '[]')
  if (conversations.value.length) {
    openConversation(conversations.value[0].id)
  } else {
    newConversation()
  }
}

function persistConversations() {
  localStorage.setItem(historyKey.value, JSON.stringify(conversations.value))
}

function newConversation() {
  const conversation = {
    id: `conv_${Date.now()}`,
    title: '新建对话',
    updatedAt: new Date().toLocaleString(),
    messages: defaultMessages()
  }
  conversations.value = [conversation, ...conversations.value]
  activeConversationId.value = conversation.id
  messages.value = conversation.messages.map((item) => ({ ...item }))
  persistConversations()
}

function openConversation(conversationId) {
  const conversation = conversations.value.find((item) => item.id === conversationId)
  if (!conversation) return
  activeConversationId.value = conversation.id
  messages.value = conversation.messages.map((item) => ({ ...item }))
}

function toggleMessageSources(message) {
  message.showSources = !message.showSources
}

function visibleSources(message) {
  const visibleIndexes = extractVisibleSourceIndexes(message.content || '')
  if (!visibleIndexes.size) return []
  return (message.sources || []).filter((source, index) => {
    const citationIndex = String(source.citation_index || index + 1)
    return visibleIndexes.has(citationIndex)
  })
}

function extractVisibleSourceIndexes(text) {
  const indexes = new Set()
  for (const line of text.split('\n')) {
    const normalized = moveSingleSourceMarkerToEnd(line)
    for (const match of normalized.matchAll(/\{\{source:(\d+)\}\}/g)) {
      indexes.add(match[1])
    }
  }
  return indexes
}

function dedupeSources(sources = []) {
  const seen = new Set()
  return sources
    .filter((source) => {
      const contentKey = (source.content || '').replace(/\s+/g, '').slice(0, 160)
      const key = `${source.document_id || source.filename}|${source.page_number || ''}|${contentKey}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .sort((left, right) => {
      const filenameCompare = (left.filename || '').localeCompare(right.filename || '', 'zh-Hans-CN')
      if (filenameCompare) return filenameCompare
      return sourcePageOrder(left) - sourcePageOrder(right)
    })
}

function sourcePageOrder(source) {
  return Number.isFinite(source.page_number) ? Number(source.page_number) : Number.MAX_SAFE_INTEGER
}

function sourcePageText(source) {
  return source.page_number ? `第 ${source.page_number} 页` : '未知页'
}

function cleanSourceContent(content = '') {
  return content
    .replace(/^[\s。．.，,、；;：:!！?？·•●○\-—–]+/, '')
    .trim()
}

function removeConversation(conversationId) {
  const nextConversations = conversations.value.filter((item) => item.id !== conversationId)
  conversations.value = nextConversations

  if (activeConversationId.value === conversationId) {
    if (nextConversations.length) {
      openConversation(nextConversations[0].id)
    } else {
      const conversation = {
        id: `conv_${Date.now()}`,
        title: '新建对话',
        updatedAt: new Date().toLocaleString(),
        messages: defaultMessages()
      }
      conversations.value = [conversation]
      activeConversationId.value = conversation.id
      messages.value = conversation.messages.map((item) => ({ ...item }))
    }
  }

  persistConversations()
}

function saveActiveConversation(latestQuestion = '') {
  if (!activeConversationId.value) {
    newConversation()
  }

  const title = latestQuestion.slice(0, 20) || '新建对话'
  conversations.value = conversations.value.map((item) => {
    if (item.id !== activeConversationId.value) return item
    return {
      ...item,
      title: item.title === '新建对话' ? title : item.title,
      updatedAt: new Date().toLocaleString(),
      messages: messages.value.map((message) => ({ ...message }))
    }
  })
  persistConversations()
}
</script>

<template>
  <div v-if="!isAuthed" class="auth-page">
    <div class="auth-panel">
      <div class="auth-brand">
        <div class="brand">GraphRAG</div>
        <p>基于 LangChain + GraphDB 的 RAG 文档问答系统</p>
      </div>

      <div class="auth-switch">
        <button :class="{ active: authMode === 'login' }" @click="switchAuthMode('login')">登录</button>
        <button :class="{ active: authMode === 'register' }" @click="switchAuthMode('register')">注册</button>
      </div>

      <form class="auth-form" @submit.prevent="submitAuth">
        <label>
          用户名
          <input v-model="authForm.username" placeholder="请输入用户名" />
        </label>
        <label>
          密码
          <input v-model="authForm.password" placeholder="至少 6 位" type="password" />
        </label>
        <p v-if="authMessage" class="auth-error">{{ authMessage }}</p>
        <button type="submit">{{ authMode === 'login' ? '登录' : '注册并登录' }}</button>
      </form>
    </div>
  </div>

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div>
          <div class="brand">GraphRAG</div>
          <div class="sub-brand">文档知识库</div>
        </div>
        <button class="logout-pill" @click="logout">退出登录</button>
      </div>

      <section class="library-card" :class="{ 'has-files': documents.length }">
        <input
          ref="fileInput"
          class="hidden-file-input"
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          @change="onFileChange"
        />

        <div class="uploaded-panel">
          <button class="new-chat-btn" @click="newConversation">新建对话</button>

          <div class="dashed-box history-box">
            <div class="history-title">对话历史</div>
            <div class="history-list">
              <div
                v-for="conversation in conversations"
                :key="conversation.id"
                class="history-item"
                :class="{ active: activeConversationId === conversation.id }"
              >
                <button class="history-open" @click="openConversation(conversation.id)">
                  <strong>{{ conversation.title }}</strong>
                  <span>{{ conversation.updatedAt }}</span>
                </button>
                <button
                  class="delete-btn"
                  title="删除对话"
                  aria-label="删除对话"
                  @click.stop="removeConversation(conversation.id)"
                >
                  ×
                </button>
              </div>
            </div>
          </div>

          <div class="dashed-box files-box">
            <div class="section-title">
              <span>已上传文件</span>
              <small>{{ selectedCount }} 个已选择</small>
            </div>

            <div class="file-list">
              <button
                class="file-item all-files"
                :class="{ active: documents.length && selectedDocumentIds.length === documents.length }"
                @click="toggleAllDocuments"
              >
                <span
                  class="checkbox"
                  :class="{ checked: documents.length && selectedDocumentIds.length === documents.length }"
                ></span>
                <span class="file-meta">
                  <strong>所有文件</strong>
                </span>
              </button>
              <div
                v-for="doc in documents"
                :key="doc.document_id"
                class="file-item"
                :class="{ active: selectedDocumentIds.includes(doc.document_id) }"
              >
                <span
                  class="file-select"
                  @click="toggleDocument(doc.document_id)"
                >
                  <span class="checkbox" :class="{ checked: selectedDocumentIds.includes(doc.document_id) }"></span>
                  <span class="file-meta">
                    <strong>{{ doc.filename }}</strong>
                  </span>
                </span>
                <button
                  class="delete-btn"
                  title="删除文件"
                  aria-label="删除文件"
                  @click.stop="removeDocument(doc.document_id)"
                >
                  ×
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="status">{{ uploadStatus }}</div>
        <button class="upload-action" :disabled="isUploading" @click="openFilePicker">
          {{ isUploading ? '上传中...' : '上传文件' }}
        </button>
      </section>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="title-group">
          <h1>RAG 文档问答</h1>
        </div>

        <div class="right-controls">
          <div class="info-card user-only">
            <span>用户名</span>
            <strong>{{ currentUser }}</strong>
          </div>
          <div class="info-card">
            <span>知识库</span>
            <strong>{{ knowledgeBaseLabel }}</strong>
          </div>
          <div class="info-card">
            <span>数据库</span>
            <strong>Chroma + Neo4j</strong>
          </div>
          <div class="info-card status-card">
            <span>运行状态</span>
            <strong>{{ health }}</strong>
          </div>
        </div>
      </header>

      <section ref="chatAreaEl" class="chat-area">
        <div class="messages">
          <div
            v-for="(message, index) in messages"
            :key="index"
            class="message-row"
            :class="message.role"
          >
            <div v-if="message.role === 'assistant'" class="avatar">AI</div>
            <div
              v-if="message.role === 'assistant'"
              class="bubble markdown-body"
            >
              <div v-if="message.isStreaming && !message.content" class="typing-loader">
                <span></span>
                <span></span>
                <span></span>
                <em>正在检索并生成回答</em>
              </div>
              <div v-else v-html="renderMarkdown(message.content, message.sources)"></div>
              <div v-if="visibleSources(message).length" class="source-tools">
                <button class="source-toggle" @click="toggleMessageSources(message)">
                  {{ message.showSources ? '收起来源' : `来源 ${visibleSources(message).length}` }}
                </button>
                <div v-if="message.showSources" class="source-panel">
                  <div
                    v-for="(source, sourceIndex) in visibleSources(message)"
                    :key="`${source.document_id}-${source.chunk_id}-${sourceIndex}`"
                    class="source-card"
                  >
                    <div class="source-head">
                      <strong>{{ source.filename }}</strong>
                      <span>{{ sourcePageText(source) }}</span>
                    </div>
                    <p>{{ cleanSourceContent(source.content) }}</p>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="bubble">{{ message.content }}</div>
            <div v-if="message.role === 'user'" class="avatar user-avatar">我</div>
          </div>
        </div>
      </section>

      <footer class="composer">
        <textarea
          v-model="question"
          placeholder="输入消息，Ctrl + Enter 发送"
          @keydown="handleKeydown"
        ></textarea>
        <button class="send-btn" :disabled="isAsking" @click="sendQuestion">
          {{ isAsking ? '生成中' : '发送' }}
        </button>
      </footer>
    </main>
  </div>
</template>

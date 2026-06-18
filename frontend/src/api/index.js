import request from './request'

// ===== 认证 =====
export function login(role, username, password) {
  return request.post(`/${role}/login`, { username, password })
}

export function registerStudent(data) {
  return request.post('/student/register', data)
}

// ===== 学生端 =====
export function submitFeedback(data) {
  return request.post('/student/feedback', data)
}

export function getConversations(page = 1, pageSize = 10) {
  return request.get('/student/conversations', { params: { page, page_size: pageSize } })
}

export function getConversation(id) {
  return request.get(`/student/conversation/${id}`)
}

export function createConversation() {
  return request.post('/student/conversation')
}

export function deleteConversation(id) {
  return request.delete(`/student/conversation/${id}`)
}

export function pinConversation(id) {
  return request.patch(`/student/conversation/${id}/pin`)
}

export function getChatHistory(limit = 50) {
  return request.get('/student/history', { params: { limit } })
}

export function multimodalUpload(file) {
  const form = new FormData()
  form.append('file', file)
  return request.post('/student/multimodal/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

export function multimodalQuery(data) {
  return request.post('/student/multimodal/query', data)
}

export function multimodalQueryStream(data) {
  return request.post('/student/multimodal/query/stream', data, {
    responseType: 'stream',
    headers: { Accept: 'text/event-stream' },
    timeout: 180000,
  })
}

export function multimodalModels() {
  return request.get('/student/multimodal/models')
}

// 拍照搜题：图片+文字均可，返回 { extracted_text, analysis, web_sources }
export function photoSearch(file, query = '') {
  const form = new FormData()
  if (file) form.append('file', file)
  if (query) form.append('query', query)
  return request.post('/student/photo-search', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

// ===== 学生Agent =====
export function studentAgentQuery(data) {
  return request.post('/student/agent/query', data, { timeout: 120000 })
}

export function getStudentAgentTools() {
  return request.get('/student/agent/tools')
}

// ===== 学生Agent 流式查询 (SSE) =====
import { createSSEConnection } from './sse'

/**
 * 学生端 Agent 流式查询（SSE, POST）
 * @param {object} data - { query: string, conversation_id?: string, images?: string[] }
 * @param {function} onEvent - (type: string, data: object) => void
 * @param {function} onError - (message: string) => void
 * @param {function} onDone - () => void
 * @returns {{ close: () => void }}
 */
export function connectAgentSSE(data, onEvent, onError, onDone) {
  const baseUrl = import.meta.env.VITE_API_BASE || ''
  return createSSEConnection({
    url: `${baseUrl}/api/v1/student/agent/query/stream`,
    method: 'POST',
    body: data,
    onEvent,
    onError,
    onDone,
  })
}

/**
 * 语音转文字：上传音频文件，返回识别文字
 * @param {Blob} audioBlob - 录音 blob
 * @returns {Promise<{text: string}>}
 */
export function voiceToText(audioBlob) {
  const form = new FormData()
  form.append('audio', audioBlob, 'recording.wav')
  return request.post('/agent/voice-to-text', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  })
}

// ===== 智能批改 =====
export function submitGrading(data) {
  return request.post('/student/agent/grade', data, { timeout: 180000 })
}

/**
 * 学生端 智能批改 流式查询（SSE, POST）
 * @param {object} data - 批改请求参数
 * @param {function} onEvent - (type: string, data: object) => void
 * @param {function} onError - (message: string) => void
 * @param {function} onDone - () => void
 * @returns {{ close: () => void }}
 */
export function connectGradeSSE(data, onEvent, onError, onDone) {
  const baseUrl = import.meta.env.VITE_API_BASE || ''
  return createSSEConnection({
    url: `${baseUrl}/api/v1/student/agent/grade/stream`,
    method: 'POST',
    body: data,
    onEvent,
    onError,
    onDone,
  })
}

// ===== 错题集 =====
export function getWrongBook(subject) {
  return request.get('/student/wrong-book', { params: { subject } })
}

export function getWrongBookStats() {
  return request.get('/student/wrong-book/stats')
}

export function deleteWrongBook(id) {
  return request.delete(`/student/wrong-book/${id}`)
}

export function getAnalogyQuestions(id) {
  return request.post(`/student/wrong-book/${id}/analogy`, {}, { timeout: 120000 })
}

export function getEbbinghausCurve() {
  return request.get('/student/wrong-book/ebbinghaus')
}

export function reviewWrongQuestion(id) {
  return request.post(`/student/wrong-book/${id}/review`)
}

// ===== 知识图谱 =====
export function getKnowledgeGraphData(subject, grade) {
  const params = {}
  if (subject) params.subject = subject
  if (grade) params.grade = grade
  return request.get('/student/graph/data', { params })
}

export function getKnowledgeGraphStats(grade) {
  const params = {}
  if (grade) params.grade = grade
  return request.get('/student/graph/stats', { params })
}

export function getEntityDetail(name) {
  return request.get(`/student/graph/entity/${encodeURIComponent(name)}`)
}

// ===== 公共接口 =====
export function query(data) {
  return request.post('/query', data)
}

export function uploadDocuments(files, kbId = null) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  const params = {}
  if (kbId) params.kb_id = kbId
  return request.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
    params,
  })
}

export function getDocuments(page = 1, pageSize = 10) {
  return request.get('/documents', { params: { page, page_size: pageSize } })
}

export function getStats() {
  return request.get('/stats')
}

export function getFaq(page = 1, pageSize = 20) {
  return request.get('/faq', { params: { page, page_size: pageSize } })
}

export function getHealth() {
  return request.get('/health')
}
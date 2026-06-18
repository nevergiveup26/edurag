import request from './request'
import { createSSEConnection } from './sse'

// ===== 管理端 =====
export function getAdminStats() {
  return request.get('/admin/stats')
}

export function importFaq() {
  return request.post('/admin/faq/import')
}

export function deleteDocument(id) {
  return request.delete(`/admin/documents/${id}`)
}

export function getDocument(id) {
  return request.get(`/admin/documents/${id}`)
}

export function runEvaluation() {
  return request.post('/admin/evaluate', {}, { timeout: 180000 })
}

export function getEvalSamples() {
  return request.get('/admin/evaluate/samples')
}

export function runRagasEvaluation(data) {
  return request.post('/admin/evaluate/ragas', data || {}, { timeout: 180000 })
}

export function getRagasSamples() {
  return request.get('/admin/evaluate/ragas/samples')
}

// ===== SSE 流式评测 =====

export function connectEvalSSE(url, onEvent, onError) {
  let sessionId = null
  const baseUrl = import.meta.env.VITE_API_BASE || ''
  const conn = createSSEConnection({
    url: `${baseUrl}/api/v1${url}`,
    method: 'GET',
    onEvent,
    onError,
    onSessionId: (sid) => { sessionId = sid },
  })
  return { ...conn, getSessionId: () => sessionId }
}

// ===== 评测历史管理 =====

export function getEvalHistory(evalType) {
  return request.get('/admin/evaluate/history', { params: { eval_type: evalType } })
}

export function getEvalHistoryDetail(id) {
  return request.get(`/admin/evaluate/history/${id}`)
}

export function deleteEvalHistory(id) {
  return request.delete(`/admin/evaluate/history/${id}`)
}

export function compareEvalHistory(id1, id2) {
  return request.post('/admin/evaluate/history/compare', { id1, id2 })
}

export function cancelEvaluation(sessionId) {
  return request.post(`/admin/evaluate/cancel/${sessionId}`)
}

export async function downloadEvalPdf(id) {
  const blob = await request.get(`/admin/evaluate/history/${id}/export/pdf`, {
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', `evaluation_${id}.pdf`)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

// 知识库
export function createKB(data) {
  return request.post('/admin/kb', data)
}

export function listKB(params) {
  return request.get('/admin/kb', { params })
}

export function getKB(id) {
  return request.get(`/admin/kb/${id}`)
}

export function updateKB(id, data) {
  return request.put(`/admin/kb/${id}`, data)
}

export function deleteKB(id) {
  return request.delete(`/admin/kb/${id}`)
}

export function getKBStats(id) {
  return request.get(`/admin/kb/${id}/stats`)
}

export function addDocsToKB(id, docIds) {
  return request.post(`/admin/kb/${id}/documents`, { doc_ids: docIds })
}

export function getKBDocuments(id, page, pageSize) {
  return request.get(`/admin/kb/${id}/documents`, { params: { page, page_size: pageSize } })
}

// 追踪
export function getTraces(limit = 20) {
  return request.get('/admin/traces', { params: { limit } })
}

export function getTraceDetail(id) {
  return request.get(`/admin/traces/${id}`)
}


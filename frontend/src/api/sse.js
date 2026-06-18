/**
 * SSE 流式连接公共模块
 *
 * 统一封装基于 fetch + ReadableStream 的 SSE 事件解析逻辑，
 * 消除 connectAgentSSE / connectGradeSSE / connectEvalSSE 三处重复代码。
 */
import { getActiveToken } from '@/stores/auth'

/**
 * @param {object} opts
 * @param {string} opts.url - 完整的 SSE 端点 URL
 * @param {string} [opts.method='POST'] - HTTP 方法
 * @param {object} [opts.body] - 请求体（JSON.stringify 后发送）
 * @param {function} opts.onEvent - (eventType: string, data: object) => void
 * @param {function} [opts.onError] - (message: string) => void
 * @param {function} [opts.onDone] - () => void
 * @param {function} [opts.onSessionId] - (sessionId: string) => void
 * @returns {{ close: () => void }}
 */
export function createSSEConnection(opts) {
  const { url, method = 'POST', body, onEvent, onError, onDone, onSessionId } = opts

  const token = getActiveToken()
  if (!token) {
    onError && onError('请先登录')
    return { close: () => {} }
  }

  let aborted = false
  let controller = null

  async function connect() {
    try {
      controller = new AbortController()
      const fetchOpts = {
        method,
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'text/event-stream',
        },
        signal: controller.signal,
      }
      if (method === 'POST') {
        fetchOpts.headers['Content-Type'] = 'application/json'
      }
      if (body !== undefined) {
        fetchOpts.body = JSON.stringify(body)
      }

      const resp = await fetch(url, fetchOpts)

      if (!resp.ok) {
        const errorText = await resp.text().catch(() => '')
        onError && onError(`请求失败 (${resp.status}): ${errorText || resp.statusText}`)
        return
      }

      if (onSessionId) {
        const sid = resp.headers.get('X-Session-Id')
        if (sid) onSessionId(sid)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let eventType = ''

      while (!aborted) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            try {
              const payload = JSON.parse(line.slice(6))
              onEvent && onEvent(eventType || payload.type, payload)
            } catch (_) { /* skip parse errors */ }
            eventType = ''
          }
        }
      }
      onDone && onDone()
    } catch (e) {
      if (e.name !== 'AbortError') {
        onError && onError('连接中断: ' + (e.message || '未知错误'))
      }
    }
  }

  connect()

  return {
    close: () => {
      aborted = true
      if (controller) controller.abort()
    },
  }
}

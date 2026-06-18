/**
 * E2E 测试：学生问答核心流程
 *
 * 覆盖：登录 → 聊天界面加载 → 发送问题 → 接收流式回答
 * 所有 API 通过 Playwright route 拦截 mock，不依赖真实后端。
 */
import { test, expect } from '@playwright/test'

// ======================== helpers ========================

function b64url(str) {
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
function makeToken(payload) {
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = b64url(JSON.stringify(payload))
  return `${header}.${body}.fakesig`
}

const STUDENT_TOKEN = makeToken({
  user_id: 'stu_e2e', username: 'teststudent',
  role: 'student', exp: Math.floor(Date.now() / 1000) + 3600,
})
const STUDENT_USER = { id: 'stu_e2e', username: 'teststudent', role: 'student' }

function sseBody(events) {
  return events.map(e => {
    const lines = []
    if (e.event) lines.push(`event: ${e.event}`)
    lines.push(`data: ${JSON.stringify(e.data)}`)
    return lines.join('\n')
  }).join('\n\n') + '\n\n'
}

// ======================== Mock setup ========================

async function setupStudentFlowMocks(page) {
  // 单一 catch-all 路由：内部按 URL 分支处理，避免 Playwright 多路由 FIFO 不确定性
  await page.route('**/api/v1/**', async (route) => {
    const url = route.request().url()

    // 放过 login/register，让 auth mock 处理
    if (url.includes('/login') || url.includes('/register')) {
      return route.fallback()
    }

    // Agent tools
    if (url.includes('/student/agent/tools')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          tools: [
            { type: 'calculator', label: '计算器', icon: 'cpu' },
            { type: 'dictionary', label: '词典', icon: 'document' },
          ],
        }),
      })
    }

    // SSE 流式回答
    if (url.includes('/student/agent/query/stream')) {
      const body = sseBody([
        { event: 'status',  data: { content: '正在分析问题...', type: 'status' } },
        { event: 'token',   data: { content: '你好！', type: 'token' } },
        { event: 'token',   data: { content: '我是 EduRAG 学习助手。', type: 'token' } },
        { event: 'done',    data: { conversation_id: 'conv_e2e_001', type: 'done' } },
      ])
      return route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body,
      })
    }

    // 会话查询
    if (url.includes('/student/conversation')) {
      return route.fulfill({ status: 200, body: JSON.stringify({ messages: [] }) })
    }

    // 其余 API：返回 200，阻止到达真实后端
    return route.fulfill({ status: 200, body: JSON.stringify({}) })
  })

  // 登录 mock 作为独立路由（先注册，确保优先级）
  await page.route('**/api/v1/student/login', async (route) => {
    await route.fulfill({
      status: 200,
      body: JSON.stringify({ message: '登录成功', token: STUDENT_TOKEN, user: STUDENT_USER }),
    })
  })
}

// ======================== Tests ========================

test('学生登录后能看到聊天界面', async ({ page }) => {
  await setupStudentFlowMocks(page)
  await page.goto('/login')

  await page.locator('input[type="text"]').first().fill('teststudent')
  await page.locator('input[type="password"]').fill('correctpass')
  await page.locator('.login-btn').click()

  await expect(page).toHaveURL(/\/student/, { timeout: 10000 })
  await expect(page.locator('.agent-input-area input, .chat-input-filled input').first()).toBeVisible({ timeout: 5000 })
})

test('学生发送问题后看到流式回答', async ({ page }) => {
  await setupStudentFlowMocks(page)

  // 直接注入 token 跳过登录
  await page.goto('/login')
  await page.evaluate(
    ({ token, user }) => {
      localStorage.setItem('edurag_token_student', token)
      localStorage.setItem('edurag_user_student', JSON.stringify(user))
    },
    { token: STUDENT_TOKEN, user: STUDENT_USER },
  )

  await page.goto('/student/home')
  await expect(page).toHaveURL(/\/student/, { timeout: 10000 })
  await page.waitForTimeout(1000)

  const inputArea = page.locator('.agent-input-area input, .chat-input-filled input').first()
  await inputArea.fill('你好，介绍一下自己')
  await page.waitForTimeout(300)
  await page.locator('.send-btn').click()

  await expect(page.locator('text=你好！').first()).toBeVisible({ timeout: 8000 })
  await expect(page.locator('text=EduRAG 学习助手').first()).toBeVisible({ timeout: 3000 })
})

test('学生发送问题后能看到思考链', async ({ page }) => {
  await setupStudentFlowMocks(page)

  await page.goto('/login')
  await page.evaluate(
    ({ token, user }) => {
      localStorage.setItem('edurag_token_student', token)
      localStorage.setItem('edurag_user_student', JSON.stringify(user))
    },
    { token: STUDENT_TOKEN, user: STUDENT_USER },
  )

  await page.goto('/student/home')
  await expect(page).toHaveURL(/\/student/, { timeout: 10000 })
  await page.waitForTimeout(1000)

  const inputArea = page.locator('.agent-input-area input, .chat-input-filled input').first()
  await inputArea.fill('测试思考链')
  await page.waitForTimeout(300)
  await page.locator('.send-btn').click()

  await expect(page.locator('text=正在分析问题...').first()).toBeVisible({ timeout: 8000 })
})

/**
 * E2E 测试：登录流程 + 路由守卫 + 多标签页回归
 *
 * 不依赖真实后端，所有 API 通过 Playwright route 拦截 mock。
 * 多标签页场景使用同一 browser context 的两个 page（共享 localStorage）。
 */
import { test, expect } from '@playwright/test'

// ======================== helpers ========================

function makeToken(payload) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${header}.${body}.fakesig`
}

const STUDENT_TOKEN = makeToken({
  user_id: 'stu_e2e', username: 'teststudent',
  role: 'student', exp: Math.floor(Date.now() / 1000) + 3600,
})
const ADMIN_TOKEN = makeToken({
  user_id: 'admin_e2e', username: 'testadmin',
  role: 'admin', exp: Math.floor(Date.now() / 1000) + 3600,
})
const STUDENT_USER = { id: 'stu_e2e', username: 'teststudent', role: 'student' }
const ADMIN_USER = { id: 'admin_e2e', username: 'testadmin', role: 'admin' }

// ======================== API mocking ========================

function setupAuthMocks(page) {
  return Promise.all([
    page.route('**/api/v1/student/login', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}')
      if (body.username === 'wronguser') {
        return route.fulfill({ status: 401, body: JSON.stringify({ detail: '学号或密码错误' }) })
      }
      return route.fulfill({
        status: 200,
        body: JSON.stringify({ message: '登录成功', token: STUDENT_TOKEN, user: STUDENT_USER }),
      })
    }),
    page.route('**/api/v1/admin/login', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}')
      if (body.username === 'wrongadmin') {
        return route.fulfill({ status: 401, body: JSON.stringify({ detail: '用户名或密码错误' }) })
      }
      return route.fulfill({
        status: 200,
        body: JSON.stringify({ message: '登录成功', token: ADMIN_TOKEN, user: ADMIN_USER }),
      })
    }),
    // 拦截所有非登录 API 请求，阻止其到达真实后端。
    // 真实后端会验证 JWT 签名（测试 token 签名是 fakesig），返回 401，
    // 触发 request.js 响应拦截器清除 localStorage token。
    page.route('**/api/v1/**', async (route) => {
      const url = route.request().url()
      // 放过 login/register 请求，让上面的专用 mock 处理
      if (url.includes('/login') || url.includes('/register')) {
        return route.fallback()
      }
      return route.fulfill({ status: 200, body: JSON.stringify({}) })
    }),
  ])
}

// ======================== 页面渲染 ========================

test('登录页渲染正常', async ({ page }) => {
  await page.goto('/login')
  await expect(page.locator('input[type="text"]').first()).toBeVisible()
  await expect(page.locator('input[type="password"]')).toBeVisible()
  await expect(page.locator('.login-btn')).toBeVisible()
})

// ======================== 登录流程 ========================

test('学生登录成功 → 跳转到 /student/home', async ({ page }) => {
  await setupAuthMocks(page)
  await page.goto('/login')

  await page.locator('input[type="text"]').first().fill('teststudent')
  await page.locator('input[type="password"]').fill('correctpass')
  await page.locator('.login-btn').click()

  await expect(page).toHaveURL(/\/student/, { timeout: 10000 })
})

test('管理登录成功 → 跳转到 /admin/dashboard', async ({ page }) => {
  await setupAuthMocks(page)
  await page.goto('/login')

  // 切换到管理端 tab
  await page.locator('.role-tab').nth(1).click()
  await page.locator('input[type="text"]').first().fill('testadmin')
  await page.locator('input[type="password"]').fill('correctpass')
  await page.locator('.login-btn').click()

  await expect(page).toHaveURL(/\/admin/, { timeout: 10000 })
})

test('密码错误 → 显示错误提示', async ({ page }) => {
  await setupAuthMocks(page)
  await page.goto('/login')

  await page.locator('input[type="text"]').first().fill('wronguser')
  await page.locator('input[type="password"]').fill('wrongpass')
  await page.locator('.login-btn').click()

  await expect(page.locator('.el-message--error, .el-message__content').first()).toBeVisible({ timeout: 5000 })
})

test('管理员登录被 403 拒绝后停留在登录页', async ({ page }) => {
  await setupAuthMocks(page)
  await page.goto('/login')

  // 用学生账号登录管理端（mock 到路由时返回 403）
  await page.route('**/api/v1/admin/login', async (route) => {
    return route.fulfill({ status: 403, body: JSON.stringify({ detail: '非管理员账号' }) })
  })
  await page.locator('.role-tab').nth(1).click()
  await page.locator('input[type="text"]').first().fill('studentuser')
  await page.locator('input[type="password"]').fill('correctpass')
  await page.locator('.login-btn').click()

  // 应该还在 /login
  await expect(page).toHaveURL(/\/login/)
})

// ======================== 路由守卫 ========================

test('未登录访问 /student/home → 重定向到 /login', async ({ page }) => {
  await page.goto('/student/home')
  await expect(page).toHaveURL(/\/login/)
})

test('未登录访问 /admin/dashboard → 重定向到 /login', async ({ page }) => {
  await page.goto('/admin/dashboard')
  await expect(page).toHaveURL(/\/login/)
})

// ======================== 多标签页回归测试 ========================

test('学生端不被管理端登录挤出（多标签页场景）', async ({ context }) => {
  // ── Tab A: 学生端 ──
  const pageA = await context.newPage()
  // 必须 mock API，否则组件 onMounted 的 API 调用会到达真实后端，
  // 后端返回 401 → request.js 拦截器清除 localStorage token
  await setupAuthMocks(pageA)
  await pageA.goto('/login')

  await pageA.evaluate(
    ({ token, user }) => {
      localStorage.setItem('edurag_token_student', token)
      localStorage.setItem('edurag_user_student', JSON.stringify(user))
    },
    { token: STUDENT_TOKEN, user: STUDENT_USER },
  )

  await pageA.goto('/student/home')
  await expect(pageA).not.toHaveURL(/\/login/)
  await expect(pageA).toHaveURL(/\/student/)

  // ── Tab B: 管理端 ──
  // 从 pageA 注入 admin token（同一 origin 共享 localStorage），
  // 这样 pageB 只需直接导航到 admin dashboard，完全避开 Login 页面
  await pageA.evaluate(
    ({ token, user }) => {
      localStorage.setItem('edurag_token_admin', token)
      localStorage.setItem('edurag_user_admin', JSON.stringify(user))
    },
    { token: ADMIN_TOKEN, user: ADMIN_USER },
  )

  // 验证两个 token 都存在
  const bothTokens = await pageA.evaluate(() => ({
    stu: localStorage.getItem('edurag_token_student'),
    adm: localStorage.getItem('edurag_token_admin'),
  }))
  expect(bothTokens.stu).not.toBeNull()
  expect(bothTokens.adm).not.toBeNull()

  // pageB 直接导航到管理端，不经过 /login
  const pageB = await context.newPage()
  await setupAuthMocks(pageB)
  await pageB.goto('/admin/dashboard')
  await expect(pageB).not.toHaveURL(/\/login/)
  await expect(pageB).toHaveURL(/\/admin/)

  // ── 切回 Tab A：核心回归 ──
  // 管理端写入 token 后，学生端 token 不应被清除
  const afterAdmin = await pageA.evaluate(() => ({
    stu: localStorage.getItem('edurag_token_student'),
    adm: localStorage.getItem('edurag_token_admin'),
  }))
  expect(afterAdmin.stu).not.toBeNull()
  expect(afterAdmin.adm).not.toBeNull()

  // 学生端继续导航——路由守卫应能读到 token
  await pageA.goto('/student/history')
  await expect(pageA).not.toHaveURL(/\/login/)
  await expect(pageA).toHaveURL(/\/student\/history/)
})

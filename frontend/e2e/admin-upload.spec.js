/**
 * E2E 测试：管理端文档上传流程
 *
 * 覆盖：管理登录 → 上传页面加载 → 选择文件 → 上传成功
 * 所有 API 通过 Playwright route 拦截 mock。
 */
import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// ======================== helpers ========================

function b64url(str) {
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
function makeToken(payload) {
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = b64url(JSON.stringify(payload))
  return `${header}.${body}.fakesig`
}

const ADMIN_TOKEN = makeToken({
  user_id: 'admin_e2e', username: 'testadmin',
  role: 'admin', exp: Math.floor(Date.now() / 1000) + 3600,
})
const ADMIN_USER = { id: 'admin_e2e', username: 'testadmin', role: 'admin' }

// ======================== Mock setup ========================

async function setupAdminUploadMocks(page) {
  // 单一 catch-all：内部按 URL 分支处理
  await page.route('**/api/v1/**', async (route) => {
    const url = route.request().url()

    // 放过 login/register
    if (url.includes('/login') || url.includes('/register')) {
      return route.fallback()
    }

    // 知识库列表
    if (url.includes('/admin/kb')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          knowledge_bases: [
            { kb_id: 'kb_001', name: '数学题库', category: 'math' },
            { kb_id: 'kb_002', name: '英语题库', category: 'english' },
          ],
        }),
      })
    }

    // 文档上传
    if (url.includes('/upload')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          documents: [
            { id: 'doc_001', filename: 'test.pdf', status: 'success' },
          ],
        }),
      })
    }

    // 其余 API
    return route.fulfill({ status: 200, body: JSON.stringify({}) })
  })

  // 管理登录
  await page.route('**/api/v1/admin/login', async (route) => {
    await route.fulfill({
      status: 200,
      body: JSON.stringify({ message: '登录成功', token: ADMIN_TOKEN, user: ADMIN_USER }),
    })
  })
}

// ======================== Tests ========================

test('管理员登录后能看到上传页面', async ({ page }) => {
  await setupAdminUploadMocks(page)
  await page.goto('/login')

  // 切换到管理端
  await page.locator('.role-tab').nth(1).click()
  await page.locator('input[type="text"]').first().fill('testadmin')
  await page.locator('input[type="password"]').fill('admin123')
  await page.locator('.login-btn').click()

  await expect(page).toHaveURL(/\/admin/, { timeout: 10000 })

  // 导航到上传页
  await page.goto('/admin/upload')
  await page.waitForTimeout(1000)

  await expect(page.locator('text=文档上传').first()).toBeVisible({ timeout: 5000 })
  // 知识库选择器可见
  await expect(page.locator('.kb-select').first()).toBeVisible({ timeout: 3000 })
})

test('管理员选择文件后能上传成功', async ({ page }) => {
  await setupAdminUploadMocks(page)

  // 注入 token 跳过登录
  await page.goto('/login')
  await page.evaluate(
    ({ token, user }) => {
      localStorage.setItem('edurag_token_admin', token)
      localStorage.setItem('edurag_user_admin', JSON.stringify(user))
    },
    { token: ADMIN_TOKEN, user: ADMIN_USER },
  )

  await page.goto('/admin/upload')
  await page.waitForTimeout(1000)

  // 选择文件：el-upload 内部有 hidden file input
  const fileInput = page.locator('.el-upload__input')
  await fileInput.setInputFiles({
    name: 'test-document.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('fake pdf content for testing'),
  })

  // 上传按钮应该出现
  await expect(page.locator('.gradient-btn').first()).toBeVisible({ timeout: 3000 })

  // 点击上传
  await page.locator('.gradient-btn').click()

  // 等待上传结果出现
  await expect(page.locator('text=test-document.pdf').first()).toBeVisible({ timeout: 8000 })
})

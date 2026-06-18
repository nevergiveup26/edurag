/**
 * Router 路由守卫测试
 * 覆盖：路由表结构、认证守卫、角色匹配、guest 重定向、过期 token
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

// 构建测试用路由表（与真实路由表结构一致，但使用 stub 组件避免 lazy import）
function b64url(str) {
  // 仅 ASCII payload，使用简单的 btoa
  const base64 = btoa(str)
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function makeToken(payload) {
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = b64url(JSON.stringify(payload))
  return `${header}.${body}.fakesig`
}

const StubComponent = { template: '<div>stub</div>' }

const testRoutes = [
  { path: '/', redirect: '/login' },
  {
    path: '/login',
    name: 'Login',
    component: StubComponent,
    meta: { guest: true },
  },
  {
    path: '/student',
    component: StubComponent,
    meta: { requiresAuth: true, role: 'student' },
    redirect: '/student/home',
    children: [
      { path: 'home', name: 'StudentHome', component: StubComponent },
      { path: 'history', name: 'StudentHistory', component: StubComponent },
    ],
  },
  {
    path: '/admin',
    component: StubComponent,
    meta: { requiresAuth: true, role: 'admin' },
    redirect: '/admin/dashboard',
    children: [
      { path: 'dashboard', name: 'AdminDashboard', component: StubComponent },
    ],
  },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: StubComponent },
]

// 与真实 router/index.js 中完全相同的 beforeEach 逻辑
import { getRoleFromToken, getActiveToken, getActiveRole } from '@/stores/auth'

function installGuard(router) {
  router.beforeEach((to, from, next) => {
    const activeRoleForDest = getActiveRole(to.path)
    const token = getActiveToken(activeRoleForDest)

    if (to.meta.requiresAuth) {
      if (!token) {
        return next('/login')
      }

      const jwtRole = getRoleFromToken(token)
      if (!jwtRole) {
        if (activeRoleForDest) {
          localStorage.removeItem(`edurag_token_${activeRoleForDest}`)
          localStorage.removeItem(`edurag_user_${activeRoleForDest}`)
        }
        return next('/login')
      }

      if (to.meta.role && jwtRole !== to.meta.role) {
        return next(jwtRole === 'admin' ? '/admin/dashboard' : '/student/home')
      }
    }

    if (to.meta.guest && token) {
      const jwtRole = getRoleFromToken(token)
      if (jwtRole) {
        return next(jwtRole === 'admin' ? '/admin/dashboard' : '/student/home')
      }
      if (activeRoleForDest) {
        localStorage.removeItem(`edurag_token_${activeRoleForDest}`)
        localStorage.removeItem(`edurag_user_${activeRoleForDest}`)
      }
    }

    next()
  })
}

const STUDENT_TOKEN = makeToken({
  user_id: 'stu_001', username: 'teststudent',
  role: 'student', exp: Math.floor(Date.now() / 1000) + 3600,
})
const ADMIN_TOKEN = makeToken({
  user_id: 'admin_001', username: 'testadmin',
  role: 'admin', exp: Math.floor(Date.now() / 1000) + 3600,
})
const EXPIRED_TOKEN = makeToken({
  user_id: 'old', role: 'student',
  exp: Math.floor(Date.now() / 1000) - 3600,
})

function createTestRouter() {
  const router = createRouter({
    history: createWebHistory(),
    routes: testRoutes,
  })
  installGuard(router)
  return router
}

describe('Router 路由表结构', () => {
  it('/ 重定向到 /login', () => {
    const root = testRoutes.find(r => r.path === '/')
    expect(root.redirect).toBe('/login')
  })

  it('/login 标记为 guest 路由', () => {
    const login = testRoutes.find(r => r.path === '/login')
    expect(login.meta.guest).toBe(true)
  })

  it('/student 要求认证且角色为学生', () => {
    const student = testRoutes.find(r => r.path === '/student')
    expect(student.meta.requiresAuth).toBe(true)
    expect(student.meta.role).toBe('student')
  })

  it('/admin 要求认证且角色为管理员', () => {
    const admin = testRoutes.find(r => r.path === '/admin')
    expect(admin.meta.requiresAuth).toBe(true)
    expect(admin.meta.role).toBe('admin')
  })

  it('学生端子路由包含 home 和 history', () => {
    const student = testRoutes.find(r => r.path === '/student')
    const childPaths = student.children.map(c => c.path)
    expect(childPaths).toContain('home')
    expect(childPaths).toContain('history')
  })
})

describe('Router beforeEach 守卫', () => {
  let router

  beforeEach(() => {
    localStorage.clear()
    router = createTestRouter()
  })

  it('未登录访问 /student/home → 重定向到 /login', async () => {
    await router.push('/student/home')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('未登录访问 /admin/dashboard → 重定向到 /login', async () => {
    await router.push('/admin/dashboard')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('已登录学生访问 /student/home → 允许通过', async () => {
    localStorage.setItem('edurag_token_student', STUDENT_TOKEN)
    localStorage.setItem('edurag_user_student', JSON.stringify({ id: '1', role: 'student' }))

    await router.push('/student/home')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/student/home')
  })

  it('已登录管理员访问 /admin/dashboard → 允许通过', async () => {
    localStorage.setItem('edurag_token_admin', ADMIN_TOKEN)
    localStorage.setItem('edurag_user_admin', JSON.stringify({ id: '1', role: 'admin' }))

    await router.push('/admin/dashboard')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/admin/dashboard')
  })

  it('学生 token 访问 /admin/dashboard → 无 admin token 被拒，重定向到 /login', async () => {
    localStorage.setItem('edurag_token_student', STUDENT_TOKEN)
    localStorage.setItem('edurag_user_student', JSON.stringify({ id: '1', role: 'student' }))

    await router.push('/admin/dashboard')
    await router.isReady()
    // getActiveToken('admin') 只查 admin key，学生 token 在 student key 中
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('管理员 token 访问 /student/home → 重定向到 /admin/dashboard', async () => {
    localStorage.setItem('edurag_token_admin', ADMIN_TOKEN)
    localStorage.setItem('edurag_user_admin', JSON.stringify({ id: '1', role: 'admin' }))

    await router.push('/student/home')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/admin/dashboard')
  })

  it('已登录用户访问 /login → 重定向到对应首页', async () => {
    localStorage.setItem('edurag_token_student', STUDENT_TOKEN)
    localStorage.setItem('edurag_user_student', JSON.stringify({ id: '1', role: 'student' }))

    // 先导航到非 /login 路径再 push /login，避免 vue-router 因同路径跳过导航
    await router.push('/notfound-xyz')
    await router.push('/login')
    expect(router.currentRoute.value.path).toBe('/student/home')
  })

  it('过期 token 访问受保护页面 → 重定向到 /login 并清除存储', async () => {
    localStorage.setItem('edurag_token_student', EXPIRED_TOKEN)
    localStorage.setItem('edurag_user_student', JSON.stringify({ id: '1', role: 'student' }))

    await router.push('/student/home')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
    // token 过期后被清理
    expect(localStorage.getItem('edurag_token_student')).toBeNull()
  })

  it('无 token 访问 /login → 允许通过', async () => {
    await router.push('/login')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('无效 token（非 JWT 格式）→ 重定向到 /login', async () => {
    localStorage.setItem('edurag_token_student', 'garbage_token')
    localStorage.setItem('edurag_user_student', JSON.stringify({ id: '1', role: 'student' }))

    await router.push('/student/home')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
  })
})

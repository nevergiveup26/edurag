/**
 * auth.js 单元测试
 * 覆盖：JWT 解码、角色提取、token 隔离、login/logout、回归验证
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock API layer before importing auth module
vi.mock('@/api/index', () => ({
  login: vi.fn().mockResolvedValue({
    token: 'fake.jwt.token',
    user: { id: 'stu_001', username: 'testuser', role: 'student' },
  }),
}))

import {
  getRoleFromToken,
  getActiveRole,
  getActiveToken,
  getActiveUser,
  useAuthStore,
} from '@/stores/auth'

// ======================== helpers ========================

function b64url(str) {
  return btoa(unescape(encodeURIComponent(str)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function makeToken(payload) {
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = b64url(JSON.stringify(payload))
  return `${header}.${body}.fakesig`
}

const STUDENT_KEY = 'edurag_token_student'
const STUDENT_USER_KEY = 'edurag_user_student'
const ADMIN_KEY = 'edurag_token_admin'
const ADMIN_USER_KEY = 'edurag_user_admin'

beforeEach(() => {
  localStorage.clear()
})

// ======================== getRoleFromToken ========================

describe('getRoleFromToken', () => {
  it('从未过期 token 提取角色', () => {
    const token = makeToken({
      user_id: 'u1', role: 'admin',
      exp: Math.floor(Date.now() / 1000) + 3600,
    })
    expect(getRoleFromToken(token)).toBe('admin')
  })

  it('过期 token 返回 null', () => {
    const token = makeToken({
      user_id: 'u1', role: 'student',
      exp: Math.floor(Date.now() / 1000) - 3600,
    })
    expect(getRoleFromToken(token)).toBeNull()
  })

  it('无效 token 返回 null', () => {
    expect(getRoleFromToken('garbage')).toBeNull()
    expect(getRoleFromToken('')).toBeNull()
  })

  it('缺少 role 字段返回 null', () => {
    const token = makeToken({
      user_id: 'u1',
      exp: Math.floor(Date.now() / 1000) + 3600,
    })
    expect(getRoleFromToken(token)).toBeNull()
  })
})

// ======================== getActiveRole ========================

describe('getActiveRole', () => {
  it('识别 /student 路径', () => {
    expect(getActiveRole('/student/home')).toBe('student')
    expect(getActiveRole('/student/history')).toBe('student')
  })

  it('识别 /admin 路径', () => {
    expect(getActiveRole('/admin/dashboard')).toBe('admin')
    expect(getActiveRole('/admin/upload')).toBe('admin')
  })

  it('非学生/管理路径返回 null', () => {
    expect(getActiveRole('/login')).toBeNull()
    expect(getActiveRole('/')).toBeNull()
  })
})

// ======================== getActiveToken ========================

describe('getActiveToken', () => {
  it('按角色读对应 key', () => {
    localStorage.setItem(STUDENT_KEY, 'student_token_abc')
    localStorage.setItem(ADMIN_KEY, 'admin_token_xyz')
    expect(getActiveToken('student')).toBe('student_token_abc')
    expect(getActiveToken('admin')).toBe('admin_token_xyz')
  })

  it('无 token 时返回空字符串', () => {
    expect(getActiveToken('student')).toBe('')
  })

  it('不传 role 时优先返回 student token', () => {
    localStorage.setItem(STUDENT_KEY, 'stu_first')
    expect(getActiveToken()).toBe('stu_first')
  })

  it('不传 role 且无 student token 时返回 admin token', () => {
    localStorage.setItem(ADMIN_KEY, 'admin_fallback')
    expect(getActiveToken()).toBe('admin_fallback')
  })
})

// ======================== getActiveUser ========================

describe('getActiveUser', () => {
  it('在当前路径为学生时返回学生用户', () => {
    localStorage.setItem(STUDENT_USER_KEY, JSON.stringify({ id: 's1', role: 'student', username: 's' }))
    const user = getActiveUser()
    expect(user).toEqual({ id: 's1', role: 'student', username: 's' })
  })

  it('无数据时返回 null', () => {
    expect(getActiveUser()).toBeNull()
  })
})

// ======================== Pinia Store ========================

describe('useAuthStore', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAuthStore()
  })

  describe('login', () => {
    it('成功后写入正确的 localStorage key', async () => {
      const { login: mockLogin } = await import('@/api/index')
      // override default mock for this test
      mockLogin.mockResolvedValueOnce({
        token: 'student.jwt.token',
        user: { id: 'stu_002', username: 'alice', role: 'student' },
      })

      await store.login('student', 'alice', 'pass123')

      expect(localStorage.getItem(STUDENT_KEY)).toBe('student.jwt.token')
      expect(JSON.parse(localStorage.getItem(STUDENT_USER_KEY))).toEqual({
        id: 'stu_002', username: 'alice', role: 'student',
      })
    })

    it('更新 reactive state', async () => {
      const { login: mockLogin } = await import('@/api/index')
      mockLogin.mockResolvedValueOnce({
        token: 'token_x',
        user: { id: 'u1', username: 'bob', role: 'student' },
      })

      await store.login('student', 'bob', 'pass')

      expect(store.token).toBe('token_x')
      expect(store.user).toEqual({ id: 'u1', username: 'bob', role: 'student' })
      expect(store.isLoggedIn).toBe(true)
      expect(store.isStudent).toBe(true)
      expect(store.isAdmin).toBe(false)
    })

    it('登录 admin 后 isAdmin 为 true', async () => {
      const { login: mockLogin } = await import('@/api/index')
      mockLogin.mockResolvedValueOnce({
        token: 'admin.token',
        user: { id: 'a1', username: 'admin', role: 'admin' },
      })

      await store.login('admin', 'admin', 'pass')

      expect(store.isLoggedIn).toBe(true)
      expect(store.isAdmin).toBe(true)
      expect(store.isStudent).toBe(false)
      expect(store.role).toBe('admin')
    })

    it('不会清除另一角色的 token（回归：多标签页场景）', async () => {
      // 模拟管理端已登录
      localStorage.setItem(ADMIN_KEY, 'existing_admin_token')
      localStorage.setItem(ADMIN_USER_KEY, JSON.stringify({ id: 'a1', username: 'admin', role: 'admin' }))

      const { login: mockLogin } = await import('@/api/index')
      mockLogin.mockResolvedValueOnce({
        token: 'student.jwt.token',
        user: { id: 'stu_003', username: 'charlie', role: 'student' },
      })

      await store.login('student', 'charlie', 'pass')

      // 学生 token 写入成功
      expect(localStorage.getItem(STUDENT_KEY)).toBe('student.jwt.token')

      // 关键断言：管理端 token 仍然存在，没有被清掉
      expect(localStorage.getItem(ADMIN_KEY)).toBe('existing_admin_token')
      expect(JSON.parse(localStorage.getItem(ADMIN_USER_KEY))).toEqual({
        id: 'a1', username: 'admin', role: 'admin',
      })
    })
  })

  describe('logout', () => {
    it('清空所有角色的 token', async () => {
      localStorage.setItem(STUDENT_KEY, 'stu_tok')
      localStorage.setItem(STUDENT_USER_KEY, JSON.stringify({ id: 's1' }))
      localStorage.setItem(ADMIN_KEY, 'adm_tok')
      localStorage.setItem(ADMIN_USER_KEY, JSON.stringify({ id: 'a1' }))

      store.token = 'stu_tok'
      store.user = { id: 's1' }

      await store.logout()

      expect(localStorage.getItem(STUDENT_KEY)).toBeNull()
      expect(localStorage.getItem(STUDENT_USER_KEY)).toBeNull()
      expect(localStorage.getItem(ADMIN_KEY)).toBeNull()
      expect(localStorage.getItem(ADMIN_USER_KEY)).toBeNull()
      expect(store.token).toBe('')
      expect(store.user).toBeNull()
      expect(store.isLoggedIn).toBe(false)
    })
  })
})

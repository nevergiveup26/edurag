import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin } from '@/api/index'

/**
 * 解码 JWT payload（不验证签名，仅提取 role 做前端角色展示）
 * 处理包含中文等多字节 UTF-8 字符的 payload
 */
function decodeJwtPayload(token) {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    // atob 只处理 Latin-1，需手动转 UTF-8 避免中文乱码
    const binary = atob(payload)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i)
    }
    const decoded = new TextDecoder().decode(bytes)
    return JSON.parse(decoded)
  } catch {
    return null
  }
}

/**
 * 从 token 中提取真实角色（JWT 签发，不可伪造）
 * 如果 token 无效或过期，返回 null
 */
export function getRoleFromToken(token) {
  const payload = decodeJwtPayload(token)
  if (!payload) return null
  if (payload.exp && Date.now() >= payload.exp * 1000) return null
  return payload.role || null
}

// ======================== Token 存储隔离 ========================
// 🔑 关键修复：学生端和管理端各用独立的 localStorage key，
// 避免同一浏览器中两个 tab 互相覆盖 token 导致越权

const STORAGE_KEYS = {
  student: { token: 'edurag_token_student', user: 'edurag_user_student' },
  admin:   { token: 'edurag_token_admin',   user: 'edurag_user_admin' },
}

/** 根据路径判断活跃角色
 *  @param {string} [path] - 可选，用于导航过渡期间传入目标路径
 */
export function getActiveRole(path) {
  const p = path || window.location.pathname
  if (p.startsWith('/admin')) return 'admin'
  if (p.startsWith('/student')) return 'student'
  return null
}

/** 获取指定角色（或当前页面）的 token
 *  @param {string} [forRole] - 可选，显式指定角色（'student' | 'admin'）
 */
export function getActiveToken(forRole) {
  const role = forRole || getActiveRole()
  if (role) {
    return localStorage.getItem(STORAGE_KEYS[role].token) || ''
  }
  // 不在学生/管理页面（如登录页）→ 尝试两个 key，优先返回第一个有效的
  return localStorage.getItem(STORAGE_KEYS.student.token)
      || localStorage.getItem(STORAGE_KEYS.admin.token)
      || ''
}

/** 获取当前页面应使用的 user */
export function getActiveUser() {
  try {
    const role = getActiveRole()
    if (role) {
      const raw = localStorage.getItem(STORAGE_KEYS[role].user)
      return raw ? JSON.parse(raw) : null
    }
    const raw = localStorage.getItem(STORAGE_KEYS.student.user)
            || localStorage.getItem(STORAGE_KEYS.admin.user)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

// ======================== Pinia Store ========================

export const useAuthStore = defineStore('auth', () => {
  // 初始化时读当前角色对应的 token
  const role = getActiveRole()
  const _token = role
    ? (localStorage.getItem(STORAGE_KEYS[role].token) || '')
    : (localStorage.getItem(STORAGE_KEYS.student.token)
       || localStorage.getItem(STORAGE_KEYS.admin.token)
       || '')
  let _user = null
  try {
    const _rawUser = role
      ? localStorage.getItem(STORAGE_KEYS[role].user)
      : (localStorage.getItem(STORAGE_KEYS.student.user)
         || localStorage.getItem(STORAGE_KEYS.admin.user))
    _user = _rawUser ? JSON.parse(_rawUser) : null
  } catch { /* localStorage 被篡改，忽略 */ }

  // 交叉校验 JWT 与存储
  if (_token && _user) {
    const jwtRole = getRoleFromToken(_token)
    if (jwtRole && jwtRole !== _user.role) {
      _user = { ..._user, role: jwtRole }
      if (role && STORAGE_KEYS[role]) {
        localStorage.setItem(STORAGE_KEYS[role].user, JSON.stringify(_user))
      }
    }
    if (!jwtRole) {
      _user = null
      _removeTokenForRole(role)
    }
  }

  const token = ref(_token)
  const user = ref(_user)

  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isStudent = computed(() => user.value?.role === 'student')
  const username = computed(() => user.value?.username || '')
  const currentRole = computed(() => user.value?.role || '')

  async function login(loginRole, username, password) {
    const res = await apiLogin(loginRole, username, password)
    token.value = res.token
    user.value = res.user
    // 保存到当前角色对应的 key
    const keys = STORAGE_KEYS[loginRole]
    if (keys) {
      localStorage.setItem(keys.token, res.token)
      localStorage.setItem(keys.user, JSON.stringify(res.user))
    }
    return res
  }

  async function logout() {
    // 调用后端吊销 Token（best-effort，失败不阻塞）
    if (token.value) {
      try {
        await fetch('/api/v1/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token.value}` },
          body: JSON.stringify({}),
        })
      } catch { /* 忽略，清理本地状态优先 */ }
    }
    token.value = ''
    user.value = null
    for (const keys of Object.values(STORAGE_KEYS)) {
      localStorage.removeItem(keys.token)
      localStorage.removeItem(keys.user)
    }
  }

  return { token, user, isLoggedIn, isAdmin, isStudent, username, role: currentRole, login, logout }
})

function _removeTokenForRole(r) {
  if (r && STORAGE_KEYS[r]) {
    localStorage.removeItem(STORAGE_KEYS[r].token)
    localStorage.removeItem(STORAGE_KEYS[r].user)
  }
}
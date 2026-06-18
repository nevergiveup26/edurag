import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getActiveToken, getActiveRole } from '@/stores/auth'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 防止多个 401 同时触发多次跳转
let _redirectLock = false

// 请求拦截器 —— 自动注入 JWT（按角色隔离） + 防串台角色头
request.interceptors.request.use(
  (config) => {
    const token = getActiveToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器 —— 统一错误处理
request.interceptors.response.use(
  (response) => {
    // 登录成功后复位 401 跳转锁
    if (_redirectLock && response.config?.url?.includes('/login')) {
      _redirectLock = false
    }
    return response.data
  },
  (error) => {
    const status = error.response?.status
    const msg = error.response?.data?.detail || error.message

    if (status === 401) {
      if (_redirectLock) return Promise.reject(error)
      _redirectLock = true
      const role = getActiveRole()
      if (role) {
        localStorage.removeItem(`edurag_token_${role}`)
        localStorage.removeItem(`edurag_user_${role}`)
      }
      ElMessage.error('登录已过期，请重新登录')
      setTimeout(() => {
        _redirectLock = false
        window.location.href = '/login'
      }, 100)
    } else if (status === 403) {
      ElMessage.error('权限不足，请确认当前账号身份')
    } else if (status === 500) {
      ElMessage.error(`服务器错误: ${msg}`)
    } else {
      ElMessage.error(msg)
    }

    return Promise.reject(error)
  }
)

export default request
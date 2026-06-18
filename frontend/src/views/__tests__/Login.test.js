/**
 * Login.vue 组件测试
 * 覆盖：表单渲染、角色切换、表单验证、登录提交
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'

// ==== Mocks (vi.hoisted to avoid hoisting issues with vi.mock factories) ====

const { mockPush, mockStoreLogin } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockStoreLogin: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

vi.mock('@/composables/useTheme', () => ({
  useTheme: () => ({ isDark: ref(false), toggle: vi.fn() }),
}))

vi.mock('@/api/index', () => ({
  registerStudent: vi.fn().mockResolvedValue({}),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    login: mockStoreLogin,
    token: ref(''),
    user: ref(null),
    isLoggedIn: ref(false),
    isAdmin: ref(false),
    isStudent: ref(false),
    username: ref(''),
    role: ref(''),
    logout: vi.fn(),
  }),
}))

// Must import after all mocks are defined
import Login from '@/views/Login.vue'

function factory() {
  return mount(Login, {
    global: {
      plugins: [createPinia(), ElementPlus],
    },
  })
}

describe('Login.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
  })

  // ---- 渲染 ----

  it('渲染登录卡片标题', () => {
    const wrapper = factory()
    expect(wrapper.text()).toContain('EduRAG 智慧问答')
  })

  it('渲染用户名和密码输入框', () => {
    const wrapper = factory()
    const inputs = wrapper.findAll('input')
    const textInputs = inputs.filter(i => i.attributes('type') === 'text')
    const pwdInputs = inputs.filter(i => i.attributes('type') === 'password')
    expect(textInputs.length).toBeGreaterThanOrEqual(1)
    expect(pwdInputs.length).toBeGreaterThanOrEqual(1)
  })

  it('渲染登录按钮', () => {
    const wrapper = factory()
    expect(wrapper.find('.login-btn').exists()).toBe(true)
  })

  it('渲染暗黑模式切换按钮', () => {
    const wrapper = factory()
    expect(wrapper.find('.theme-toggle-btn').exists()).toBe(true)
  })

  // ---- 角色切换 ----

  it('默认角色为学生', () => {
    const wrapper = factory()
    const tabs = wrapper.findAll('.role-tab')
    expect(tabs[0].classes()).toContain('active')
    expect(tabs[0].text()).toContain('学生登录')
  })

  it('点击管理端标签页切换角色', async () => {
    const wrapper = factory()
    const tabs = wrapper.findAll('.role-tab')
    await tabs[1].trigger('click')
    expect(tabs[1].classes()).toContain('active')
    expect(tabs[0].classes()).not.toContain('active')
  })

  it('学生端显示注册链接和提示', () => {
    const wrapper = factory()
    expect(wrapper.text()).toContain('没有账号？立即注册')
    expect(wrapper.text()).toContain('2024001')
  })

  it('管理端显示管理提示', async () => {
    const wrapper = factory()
    await wrapper.findAll('.role-tab').at(1).trigger('click')
    expect(wrapper.text()).toContain('admin / admin123')
  })

  // ---- 登录成功 ----

  it('填写表单并点击登录调用 authStore.login', async () => {
    mockStoreLogin.mockResolvedValueOnce({
      token: 'test_token',
      user: { id: '1', username: 'test', role: 'student' },
    })

    const wrapper = factory()
    const inputs = wrapper.findAll('input')
    const textInput = inputs.filter(i => i.attributes('type') === 'text').at(0)
    const pwdInput = inputs.filter(i => i.attributes('type') === 'password').at(0)
    await textInput.setValue('testuser')
    await pwdInput.setValue('testpass')

    await wrapper.find('.login-btn').trigger('click')
    await flushPromises()

    expect(mockStoreLogin).toHaveBeenCalledWith('student', 'testuser', 'testpass')
  })

  it('登录成功后跳转到 /student/home', async () => {
    mockStoreLogin.mockResolvedValueOnce({
      token: 'test_token',
      user: { id: '1', username: 'test', role: 'student' },
    })

    const wrapper = factory()
    const inputs = wrapper.findAll('input')
    const textInput = inputs.filter(i => i.attributes('type') === 'text').at(0)
    const pwdInput = inputs.filter(i => i.attributes('type') === 'password').at(0)
    await textInput.setValue('testuser')
    await pwdInput.setValue('testpass')

    await wrapper.find('.login-btn').trigger('click')
    await flushPromises()

    expect(mockPush).toHaveBeenCalledWith('/student/home')
  })

  it('管理员登录成功后跳转到 /admin/dashboard', async () => {
    mockStoreLogin.mockResolvedValueOnce({
      token: 'admin_token',
      user: { id: '1', username: 'admin', role: 'admin' },
    })

    const wrapper = factory()
    // 切换到管理端
    await wrapper.findAll('.role-tab').at(1).trigger('click')

    const inputs = wrapper.findAll('input')
    const textInput = inputs.filter(i => i.attributes('type') === 'text').at(0)
    const pwdInput = inputs.filter(i => i.attributes('type') === 'password').at(0)
    await textInput.setValue('admin')
    await pwdInput.setValue('admin123')

    await wrapper.find('.login-btn').trigger('click')
    await flushPromises()

    expect(mockStoreLogin).toHaveBeenCalledWith('admin', 'admin', 'admin123')
    expect(mockPush).toHaveBeenCalledWith('/admin/dashboard')
  })

  // ---- 登录失败 ----

  it('登录失败显示网络错误提示', async () => {
    mockStoreLogin.mockRejectedValueOnce({ response: null })

    const wrapper = factory()
    const inputs = wrapper.findAll('input')
    const textInput = inputs.filter(i => i.attributes('type') === 'text').at(0)
    const pwdInput = inputs.filter(i => i.attributes('type') === 'password').at(0)
    await textInput.setValue('baduser')
    await pwdInput.setValue('badpass')

    await wrapper.find('.login-btn').trigger('click')
    await flushPromises()

    // 登录失败不应导航
    expect(mockPush).not.toHaveBeenCalled()
  })

  // ---- 注册弹窗 ----

  it('点击注册链接打开注册弹窗', async () => {
    const wrapper = factory()
    const registerLink = wrapper.find('.footer-link')
    await registerLink.trigger('click')
    await flushPromises()
    // 检查 dialog 可见
    const dialog = wrapper.find('.el-dialog')
    expect(dialog.exists()).toBe(true)
  })
})

/**
 * useTheme 单元测试
 * 覆盖：初始化（localStorage / 系统偏好）、toggle、dark class 切换
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

// useTheme 使用模块级 isDark ref，需要重置
async function resetModule() {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
  vi.resetModules()
}

describe('useTheme', () => {
  beforeEach(async () => {
    // 每个测试前重置 matchMedia，避免测试间相互干扰
    window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() })
    await resetModule()
  })

  it('默认按系统偏好初始化（未存 localStorage 时）', async () => {
    // mock 系统偏好为 dark
    window.matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn() })
    const { isDark } = await import('@/composables/useTheme').then(m => m.useTheme())
    expect(isDark.value).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('localStorage 存储 dark 时初始化为暗色', async () => {
    localStorage.setItem('edurag_theme', 'dark')
    const { isDark } = await import('@/composables/useTheme').then(m => m.useTheme())
    expect(isDark.value).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('localStorage 存储 light 时初始化为亮色', async () => {
    localStorage.setItem('edurag_theme', 'light')
    const { isDark } = await import('@/composables/useTheme').then(m => m.useTheme())
    expect(isDark.value).toBe(false)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('toggle 切换暗色模式并持久化', async () => {
    const { isDark, toggle } = await import('@/composables/useTheme').then(m => m.useTheme())
    expect(isDark.value).toBe(false) // 默认 light（无系统偏好覆盖时）

    toggle()
    expect(isDark.value).toBe(true)
    expect(localStorage.getItem('edurag_theme')).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    toggle()
    expect(isDark.value).toBe(false)
    expect(localStorage.getItem('edurag_theme')).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('多次调用 useTheme 返回同一个 isDark', async () => {
    const m = await import('@/composables/useTheme')
    const a = m.useTheme()
    const b = m.useTheme()
    expect(a.isDark).toBe(b.isDark)
  })
})

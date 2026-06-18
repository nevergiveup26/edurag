import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import NotFound from '@/views/NotFound.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

describe('NotFound.vue', () => {
  it('渲染 404 标题、描述和返回首页按钮', () => {
    const wrapper = mount(NotFound, {
      global: {
        plugins: [ElementPlus],
      },
    })
    expect(wrapper.text()).toContain('404')
    expect(wrapper.text()).toContain('页面不存在')
    expect(wrapper.text()).toContain('返回首页')
  })
})

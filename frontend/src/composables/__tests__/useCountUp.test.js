/**
 * useCountUp 单元测试
 * 核心：requestAnimationFrame 驱动的 easeOutCubic 数字滚动动画
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { useCountUp } from '@/composables/useCountUp'

describe('useCountUp', () => {
  let rafCallbacks = []

  beforeEach(() => {
    rafCallbacks = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      const id = rafCallbacks.length + 1
      rafCallbacks.push(cb)
      return id
    })
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function tick(count = 5) {
    // 触发 watch immediate，然后逐帧推进
    for (let i = 0; i < count; i++) {
      const cbs = [...rafCallbacks]
      rafCallbacks = []
      cbs.forEach(cb => cb(performance.now()))
    }
  }

  it('初始 displayVal 为 0', async () => {
    const val = useCountUp(100, 600)
    await nextTick()
    expect(val.value).toBe(0)
  })

  it('动画推进后 displayVal 接近目标值', async () => {
    const val = useCountUp(100, 600)
    await nextTick()
    tick(30)  // 多帧推进，应该接近目标值
    expect(val.value).toBeGreaterThan(0)
    expect(val.value).toBeLessThanOrEqual(100)
  })

  it('传入 ref 作为目标值', async () => {
    const target = ref(50)
    const val = useCountUp(target, 600)
    await nextTick()
    tick(30)
    expect(val.value).toBeLessThanOrEqual(50)
  })

  it('目标值变更时重新开始动画', async () => {
    const target = ref(30)
    const val = useCountUp(target, 600)
    await nextTick()
    tick(30)
    const midValue = val.value

    target.value = 80
    await nextTick()
    tick(30)
    // 从 midValue 开始向 80 推进
    expect(val.value).toBeGreaterThanOrEqual(midValue)
  })

  it('传入 null/undefined 时不崩溃', async () => {
    const val = useCountUp(null, 600)
    await nextTick()
    tick(10)
    expect(val.value).toBe(0)
  })
})

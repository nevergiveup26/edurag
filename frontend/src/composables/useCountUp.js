import { ref, watch, onBeforeUnmount, isRef } from 'vue'

/**
 * 数字滚动 composable（支持 ref / computed 传入）
 * @param {number|Ref<number>|ComputedRef<number>} endVal - 目标值或响应式对象
 * @param {number} duration - 动画时长(ms)
 */
export function useCountUp(endVal, duration = 600) {
  const displayVal = ref(0)
  let rafId = null
  let startTime = null
  let startVal = 0

  function animate(timestamp) {
    if (!startTime) startTime = timestamp
    const elapsed = timestamp - startTime
    const progress = Math.min(elapsed / duration, 1)
    // easeOutCubic
    const eased = 1 - Math.pow(1 - progress, 3)
    // 安全解包：如果 endVal 是 ref/computed，取其 .value
    const target = (isRef(endVal) ? endVal.value : endVal) || 0
    displayVal.value = startVal + (target - startVal) * eased

    if (progress < 1) {
      rafId = requestAnimationFrame(animate)
    }
  }

  function start() {
    if (rafId) cancelAnimationFrame(rafId)
    startTime = null
    startVal = displayVal.value || 0
    rafId = requestAnimationFrame(animate)
  }

  // 监听目标值变化（兼容 ref/computed/普通值）
  watch(
    () => (isRef(endVal) ? endVal.value : endVal),
    (newVal) => {
      if (newVal != null && newVal !== displayVal.value) {
        start()
      }
    },
    { immediate: true }
  )

  onBeforeUnmount(() => {
    if (rafId) cancelAnimationFrame(rafId)
  })

  return displayVal
}
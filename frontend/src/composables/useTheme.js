import { ref } from 'vue'

const isDark = ref(false)
let _initialized = false

function apply() {
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark', isDark.value)
  }
}

function initTheme() {
  if (_initialized) return
  _initialized = true
  const stored = localStorage.getItem('edurag_theme')
  if (stored === 'dark') {
    isDark.value = true
  } else if (stored === 'light') {
    isDark.value = false
  } else {
    isDark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
  }
  apply()
  // 监听系统变化
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!localStorage.getItem('edurag_theme')) {
      isDark.value = e.matches
      apply()
    }
  })
}

function toggle() {
  isDark.value = !isDark.value
  localStorage.setItem('edurag_theme', isDark.value ? 'dark' : 'light')
  apply()
}

export function useTheme() {
  initTheme()
  return { isDark, toggle }
}
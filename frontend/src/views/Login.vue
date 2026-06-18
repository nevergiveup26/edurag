<template>
  <!--
    Login.vue — Material Design 3 风格登录页
    支持学生端和管理端统一入口，含暗黑模式切换
  -->
  <div class="login-page">
    <!-- 背景装饰层 -->
    <div class="login-bg">
      <div class="bg-blob bg-blob--1"></div>
      <div class="bg-blob bg-blob--2"></div>
      <div class="bg-blob bg-blob--3"></div>
    </div>

    <!-- 暗黑模式切换按钮 -->
    <button class="theme-toggle-btn" @click="toggle()" :title="isDark ? '切换亮色模式' : '切换暗黑模式'">
      <el-icon :size="18"><Moon v-if="!isDark" /><Sunny v-else /></el-icon>
    </button>

    <!-- 登录卡片 -->
    <div class="login-card">
      <!-- Logo 区域 -->
      <div class="login-logo">
        <div class="logo-icon">🎓</div>
      </div>

      <h1 class="login-title">EduRAG 智慧问答</h1>
      <p class="login-desc">AI 驱动的智能学习助手</p>

      <!-- 角色切换标签页 -->
      <div class="role-tabs">
        <button
          class="role-tab"
          :class="{ active: role === 'student' }"
          @click="role = 'student'"
        >
          <el-icon><User /></el-icon>
          <span>学生登录</span>
        </button>
        <button
          class="role-tab"
          :class="{ active: role === 'admin' }"
          @click="role = 'admin'"
        >
          <el-icon><Setting /></el-icon>
          <span>管理员登录</span>
        </button>
      </div>

      <!-- 登录表单 -->
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        class="login-form"
        @submit.prevent="handleLogin"
      >
        <!-- 用户名 -->
        <el-form-item prop="username" class="form-item-float">
          <el-input
            v-model="form.username"
            :placeholder="role === 'student' ? '请输入学号' : '请输入管理员账号'"
            size="large"
            clearable
            class="input-filled"
          >
            <template #prefix>
              <el-icon :size="18" class="input-icon"><User /></el-icon>
            </template>
          </el-input>
        </el-form-item>

        <!-- 密码 -->
        <el-form-item prop="password" class="form-item-float">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
            class="input-filled"
            @keyup.enter="handleLogin"
          >
            <template #prefix>
              <el-icon :size="18" class="input-icon"><Lock /></el-icon>
            </template>
          </el-input>
        </el-form-item>

        <!-- 登录按钮 -->
        <el-form-item>
          <button
            class="login-btn"
            :class="{ loading: loading }"
            :disabled="loading"
            @click="handleLogin"
          >
            <span v-if="loading" class="btn-spinner"></span>
            <span v-else class="btn-content">
              <el-icon><Key /></el-icon>
              登 录
            </span>
          </button>
        </el-form-item>
      </el-form>

      <!-- 底部链接 -->
      <div class="login-footer">
        <template v-if="role === 'student'">
          <el-link type="primary" underline="never" @click="showRegister = true" class="footer-link">
            没有账号？立即注册
          </el-link>
          <p class="hint-text">测试账号：2024001 / 123456</p>
        </template>
        <template v-else>
          <p class="hint-text">测试账号：admin / admin123</p>
        </template>
      </div>
    </div>

    <!-- 注册弹窗 -->
    <el-dialog
      v-model="showRegister"
      title="学生注册"
      width="400px"
      :close-on-click-modal="false"
      class="register-dialog"
    >
      <el-form :model="regForm" :rules="regRules" ref="regFormRef" @submit.prevent="handleRegister">
        <el-form-item prop="username">
          <el-input v-model="regForm.username" placeholder="学号" size="large">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="regForm.password" type="password" placeholder="密码（至少6位）" size="large" show-password>
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item prop="display_name">
          <el-input v-model="regForm.display_name" placeholder="姓名（可选）" size="large">
            <template #prefix><el-icon><EditPen /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <button class="login-btn" :class="{ loading: regLoading }" :disabled="regLoading" @click="handleRegister">
            <span v-if="regLoading" class="btn-spinner"></span>
            <span v-else>注 册</span>
          </button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * Login.vue — 登录页逻辑
 * 使用 Pinia auth store 调用 API，JWT token 按角色隔离存储
 */
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import { registerStudent } from '@/api/index'
import { Moon, Sunny, User, Lock, Key, Setting, EditPen } from '@element-plus/icons-vue'

const router = useRouter()
const authStore = useAuthStore()
const { isDark, toggle } = useTheme()

// ---- 登录状态 ----
const role = ref('student')
const loading = ref(false)
const formRef = ref(null)
const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// ---- 注册状态 ----
const showRegister = ref(false)
const regLoading = ref(false)
const regFormRef = ref(null)
const regForm = reactive({ username: '', password: '', display_name: '' })
const regRules = {
  username: [{ required: true, message: '请输入学号', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' },
  ],
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.login(role.value, form.username, form.password)
    ElMessage.success('登录成功')
    const target = role.value === 'admin' ? '/admin/dashboard' : '/student/home'
    router.push(target)
  } catch (e) {
    if (!e.response) ElMessage.error('网络连接失败，请检查网络')
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  const valid = await regFormRef.value?.validate().catch(() => false)
  if (!valid) return

  regLoading.value = true
  try {
    await registerStudent(regForm)
    ElMessage.success('注册成功，请登录')
    showRegister.value = false
    form.username = regForm.username
    form.password = ''
  } catch (_) {
    // handled by interceptor
  } finally {
    regLoading.value = false
  }
}
</script>

<style scoped>
/* ================================================================
   Login.vue — Material Design 3 登录页样式
   设计要点：
   - 渐变背景 + 毛玻璃模糊装饰球
   - 卡片内阴影、圆角16px、微悬浮
   - 胶囊式角色切换标签页
   - 渐变提交按钮 + 加载旋转动画
   - 所有交互元素 0.25s ease-in-out 过渡
   ================================================================ */

/* ----- 背景层 ----- */
.login-page {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg,
    #165DFF 0%,
    #4080FF 25%,
    #0E42D2 60%,
    #0A32A1 100%
  );
  position: relative;
  overflow: hidden;
}

.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

/* 毛玻璃装饰球 */
.bg-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.15;
}
.bg-blob--1 {
  width: 400px; height: 400px;
  background: #6AA1FF;
  top: -100px; left: -80px;
  animation: blob-float 12s ease-in-out infinite;
}
.bg-blob--2 {
  width: 300px; height: 300px;
  background: #00B42A;
  bottom: -80px; right: -60px;
  animation: blob-float 10s ease-in-out infinite reverse;
}
.bg-blob--3 {
  width: 250px; height: 250px;
  background: #FF7D00;
  bottom: 20%; left: 60%;
  animation: blob-float 15s ease-in-out infinite;
}

@keyframes blob-float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -30px) scale(1.05); }
  66% { transform: translate(-20px, 20px) scale(0.95); }
}

/* ----- 暗黑模式切换 ----- */
.theme-toggle-btn {
  position: fixed;
  top: var(--space-6);
  right: var(--space-6);
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fff;
  cursor: pointer;
  z-index: 100;
  transition: all var(--transition-base);
}
.theme-toggle-btn:hover {
  background: rgba(255, 255, 255, 0.25);
  transform: scale(1.08);
  border-color: rgba(255, 255, 255, 0.35);
}

/* ----- 登录卡片 ----- */
.login-card {
  width: 420px;
  padding: var(--space-10) var(--space-10) var(--space-8);
  background: var(--color-surface);
  border-radius: var(--radius-2xl);
  box-shadow: var(--shadow-modal);
  position: relative;
  z-index: 1;
  animation: card-in 0.5s var(--easing-emphasized);
}

@keyframes card-in {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* Logo */
.login-logo {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-3);
}
.logo-icon {
  width: 56px;
  height: 56px;
  font-size: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--color-primary-light), var(--color-primary-bg));
  box-shadow: 0 2px 12px rgba(22, 93, 255, 0.15);
}

.login-title {
  text-align: center;
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--space-1);
  letter-spacing: -0.5px;
}

.login-desc {
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--text-base);
  margin-bottom: var(--space-6);
}

/* ----- 角色切换标签页（胶囊样式） ----- */
.role-tabs {
  display: flex;
  background: var(--color-bg);
  border-radius: var(--radius-lg);
  padding: 3px;
  margin-bottom: var(--space-6);
  gap: 3px;
}

.role-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  height: 40px;
  border: none;
  background: transparent;
  border-radius: calc(var(--radius-lg) - 2px);
  font-family: var(--font-family-base);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
}
.role-tab:hover {
  color: var(--color-text-primary);
  background: rgba(22, 93, 255, 0.04);
}
.role-tab.active {
  background: var(--color-surface);
  color: var(--color-primary);
  font-weight: var(--font-semibold);
  box-shadow: var(--shadow-card);
}

/* ----- 表单 ----- */
.login-form {
  margin-top: 0;
}

.form-item-float {
  margin-bottom: var(--space-5);
}

/* 填充式输入框 */
:deep(.input-filled .el-input__wrapper) {
  background: var(--color-bg) !important;
  border-radius: var(--radius-md) !important;
  box-shadow: 0 0 0 1px transparent inset !important;
  transition: all var(--transition-base) !important;
  height: 44px;
}
:deep(.input-filled .el-input__wrapper:hover) {
  background: var(--color-border-light) !important;
  box-shadow: 0 0 0 1px var(--color-border) inset !important;
}
:deep(.input-filled .el-input__wrapper.is-focus) {
  background: var(--color-surface) !important;
  box-shadow: 0 0 0 2px var(--color-primary) inset !important;
}
:deep(.input-filled .el-input__inner) {
  font-size: var(--text-base);
}

.input-icon {
  color: var(--color-text-tertiary);
  transition: color var(--transition-base);
}
:deep(.input-filled.is-focus .input-icon) {
  color: var(--color-primary);
}

/* ----- 登录按钮（渐变 + 加载动画） ----- */
.login-btn {
  width: 100%;
  height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), #4080FF);
  color: #fff;
  font-family: var(--font-family-base);
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: all var(--transition-base);
  position: relative;
  overflow: hidden;
}
.login-btn::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0.1) 50%,
    rgba(255, 255, 255, 0) 100%
  );
  transform: translateX(-100%);
  transition: transform 0.6s ease;
}
.login-btn:hover:not(:disabled)::after {
  transform: translateX(100%);
}
.login-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--color-primary-hover), #2B6EF7);
  box-shadow: 0 4px 20px rgba(22, 93, 255, 0.35);
  transform: translateY(-1px);
}
.login-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(22, 93, 255, 0.25);
}
.login-btn:disabled {
  cursor: not-allowed;
  opacity: 0.8;
}

.btn-content {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  letter-spacing: 0.5px;
}

/* 加载旋转动画 */
.btn-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ----- 底部链接 ----- */
.login-footer {
  text-align: center;
  margin-top: var(--space-4);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}

.footer-link {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}

.hint-text {
  font-size: var(--text-xs);
  color: var(--color-text-disabled);
  margin: 0;
}

/* ----- 暗黑模式适配 ----- */
html.dark .login-page {
  background: linear-gradient(135deg,
    #0D1B3E 0%,
    #141E3A 25%,
    #0A1226 60%,
    #060D1A 100%
  );
}
html.dark .bg-blob { opacity: 0.08; }
html.dark .login-card {
  background: var(--color-surface);
  box-shadow: var(--shadow-modal);
}
html.dark :deep(.input-filled .el-input__wrapper) {
  background: var(--color-surface-secondary) !important;
}
html.dark :deep(.input-filled .el-input__wrapper.is-focus) {
  background: var(--color-surface) !important;
}
html.dark .role-tabs {
  background: var(--color-surface-secondary);
}

/* ----- 响应式 ----- */
@media (max-width: 480px) {
  .login-card {
    width: 92%;
    padding: var(--space-6) var(--space-5) var(--space-6);
  }
  .login-title { font-size: var(--text-xl); }
}</style>
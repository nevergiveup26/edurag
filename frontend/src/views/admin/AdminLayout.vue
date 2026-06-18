<template>
  <!--
    AdminLayout.vue — 管理端布局（MD3 灵动风格）
    深蓝渐变侧栏 + 面包屑头部 + 暗黑切换 + 退出登录
  -->
  <el-container style="height: 100vh;">
    <!-- ====== 侧栏 ====== -->
    <el-aside width="230px" class="admin-sidebar">
      <!-- 星光装饰 -->
      <div class="sidebar-stars">
        <span></span><span></span><span></span><span></span><span></span><span></span><span></span>
      </div>
      <!-- Logo -->
      <div class="sidebar-brand">
        <div class="brand-icon">⚙️</div>
        <div class="brand-info">
          <div class="brand-name">EduRAG 管理</div>
          <div class="brand-user">{{ authStore.username }}</div>
        </div>
        <el-tag class="brand-role" size="small" effect="dark" round>Admin</el-tag>
      </div>

      <!-- 导航 -->
      <el-menu
        :default-active="route.path"
        router
        background-color="transparent"
        text-color="rgba(255,255,255,0.55)"
        active-text-color="#fff"
        class="sidebar-menu"
      >
        <el-menu-item index="/admin/dashboard">
          <el-icon><DataBoard /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/admin/knowledge">
          <el-icon><Collection /></el-icon>
          <span>知识库</span>
        </el-menu-item>
        <el-menu-item index="/admin/upload">
          <el-icon><Upload /></el-icon>
          <span>文档上传</span>
        </el-menu-item>
        <el-menu-item index="/admin/visualize">
          <el-icon><DataAnalysis /></el-icon>
          <span>检索可视化 & 调用链</span>
        </el-menu-item>
        <el-menu-item index="/admin/evaluate">
          <el-icon><TrendCharts /></el-icon>
          <span>RAG 评估中心</span>
        </el-menu-item>
        <el-menu-item index="/admin/eval-history">
          <el-icon><Timer /></el-icon>
          <span>评估历史</span>
        </el-menu-item>
      </el-menu>

      <!-- 底部操作 -->
      <div class="sidebar-bottom">
        <button class="sb-btn theme-btn" @click="toggle()" :title="isDark ? '亮色模式' : '暗黑模式'">
          <el-icon :size="18"><Moon v-if="!isDark" /><Sunny v-else /></el-icon>
        </button>
        <button class="sb-btn logout-btn" @click="handleLogout">
          <el-icon :size="16"><SwitchButton /></el-icon>
          <span>退出</span>
        </button>
      </div>
    </el-aside>

    <!-- ====== 主内容区 ====== -->
    <el-main class="layout-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import { ElMessage } from 'element-plus'
import {
  Sunny, Moon, DataBoard, Collection, Upload,
  DataAnalysis, TrendCharts, Timer, SwitchButton
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { isDark, toggle } = useTheme()

function handleLogout() {
  authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
/* ================================================================
   AdminLayout — 高端极简深度侧栏
   设计：深空渐变 + 星光粒子 + 玻璃态导航项 + 金线激活指示
   所有交互 0.3s cubic-bezier(0.4, 0, 0.2, 1)
   ================================================================ */

/* ----- 侧栏基础 ----- */
.admin-sidebar {
  background: linear-gradient(172deg, #090B1A 0%, #0F1133 35%, #0B0D24 65%, #080A1D 100%) !important;
  border-right: 1px solid rgba(255, 255, 255, 0.04);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* 星光粒子装饰 */
.admin-sidebar::before {
  content: '';
  position: absolute;
  top: 5%; right: 15%;
  width: 180px; height: 180px;
  border-radius: 50%;
  background: radial-gradient(circle at 60% 40%,
    rgba(75, 94, 228, 0.08) 0%,
    rgba(124, 111, 240, 0.04) 35%,
    transparent 70%);
  pointer-events: none;
}
.admin-sidebar::after {
  content: '';
  position: absolute;
  bottom: 12%; left: 5%;
  width: 120px; height: 120px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 70%,
    rgba(212, 155, 58, 0.06) 0%,
    rgba(212, 155, 58, 0.02) 50%,
    transparent 70%);
  pointer-events: none;
}

/* 星星点缀 (CSS dots) */
.sidebar-stars {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}
.sidebar-stars span {
  position: absolute;
  width: 2px; height: 2px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  animation: star-twinkle 3s ease-in-out infinite;
}
.sidebar-stars span:nth-child(1) { top: 12%; left: 18%; animation-delay: 0s; }
.sidebar-stars span:nth-child(2) { top: 28%; left: 75%; animation-delay: 0.8s; width: 1.5px; height: 1.5px; }
.sidebar-stars span:nth-child(3) { top: 45%; left: 10%; animation-delay: 1.6s; }
.sidebar-stars span:nth-child(4) { top: 62%; left: 82%; animation-delay: 2.4s; width: 1.5px; height: 1.5px; }
.sidebar-stars span:nth-child(5) { top: 80%; left: 22%; animation-delay: 0.4s; }
.sidebar-stars span:nth-child(6) { top: 8%; left: 55%; animation-delay: 2.0s; width: 1px; height: 1px; }
.sidebar-stars span:nth-child(7) { top: 70%; left: 48%; animation-delay: 1.2s; width: 1px; height: 1px; }
@keyframes star-twinkle {
  0%, 100% { opacity: 0.15; }
  50% { opacity: 0.6; }
}

/* ----- Logo 区域 ----- */
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.brand-icon {
  width: 40px; height: 40px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(75, 94, 228, 0.3), rgba(124, 111, 240, 0.15));
  box-shadow: 0 0 16px rgba(75, 94, 228, 0.2);
  flex-shrink: 0;
  position: relative;
}
.brand-icon::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: calc(var(--radius-lg) + 2px);
  background: linear-gradient(135deg, rgba(75, 94, 228, 0.4), transparent);
  z-index: -1;
}
.brand-info { flex: 1; min-width: 0; }
.brand-name {
  font-size: var(--text-base);
  font-weight: var(--font-bold);
  color: #fff;
  letter-spacing: 0.02em;
  line-height: 1.3;
}
.brand-user {
  font-size: var(--text-xs);
  color: rgba(255, 255, 255, 0.38);
  margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-weight: var(--font-medium);
}
.brand-role {
  flex-shrink: 0;
}

/* ----- 导航菜单 ----- */
.sidebar-menu {
  flex: 1;
  border-right: none !important;
  padding: var(--space-3) var(--space-2);
  overflow-y: auto;
  overflow-x: hidden;
  position: relative;
  z-index: 1;
}
.sidebar-menu .el-menu-item {
  height: 42px;
  line-height: 42px;
  margin: 2px 6px;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  padding-left: 16px !important;
  letter-spacing: 0.01em;
}
.sidebar-menu .el-menu-item:hover {
  background: rgba(255, 255, 255, 0.05) !important;
  color: rgba(255, 255, 255, 0.9) !important;
}
.sidebar-menu .el-menu-item.is-active {
  background: rgba(75, 94, 228, 0.14) !important;
  color: #fff !important;
  font-weight: var(--font-semibold);
  box-shadow: 0 0 0 1px rgba(75, 94, 228, 0.2);
  backdrop-filter: blur(8px);
}
/* 激活态金线指示器 */
.sidebar-menu .el-menu-item.is-active::before {
  content: '';
  position: absolute;
  left: 0; top: 9px; bottom: 9px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, #4B5EE4, #7C6FF0);
  box-shadow: 0 0 10px rgba(75, 94, 228, 0.5);
}
.sidebar-menu .el-menu-item .el-icon {
  font-size: 18px;
  margin-right: 2px;
}

/* 侧栏滚动条 */
.sidebar-menu::-webkit-scrollbar { width: 3px; }
.sidebar-menu::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 10px;
}

/* ----- 底部操作 ----- */
.sidebar-bottom {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.sb-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  border: none;
  cursor: pointer;
  font-family: var(--font-family-base);
  font-size: var(--text-sm);
  border-radius: var(--radius-md);
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}
.theme-btn {
  width: 38px; height: 38px;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.45);
  border-radius: var(--radius-md);
}
.theme-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.85);
}
.logout-btn {
  flex: 1;
  height: 38px;
  justify-content: center;
  background: transparent;
  color: rgba(255, 110, 110, 0.55);
  border: 1px solid rgba(255, 110, 110, 0.15);
  border-radius: var(--radius-md);
  font-weight: var(--font-medium);
}
.logout-btn:hover {
  background: rgba(255, 110, 110, 0.1);
  color: rgba(255, 130, 130, 0.9);
  border-color: rgba(255, 110, 110, 0.35);
}
</style>
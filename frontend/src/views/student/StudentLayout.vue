<template>
  <!--
    StudentLayout.vue — 学生端布局（Deep Ink 深空风格）
    深空渐变侧栏 + 星光粒子 + 玻璃态导航 + 学生品牌标识
    与管理员端共享同一设计系统，侧栏配色保持一致
  -->
  <el-container style="height: 100vh;">
    <!-- ====== 侧栏 ====== -->
    <el-aside width="230px" class="student-sidebar">
      <!-- 星光装饰 -->
      <div class="sidebar-stars">
        <span></span><span></span><span></span><span></span><span></span><span></span><span></span>
      </div>
      <!-- Logo -->
      <div class="sidebar-brand">
        <div class="brand-icon">📚</div>
        <div class="brand-info">
          <div class="brand-name">EduRAG 学习</div>
          <div class="brand-user">{{ authStore.username }}</div>
        </div>
        <el-tag class="brand-role" size="small" effect="dark" round>学员</el-tag>
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
        <el-menu-item index="/student/home">
          <el-icon><ChatLineSquare /></el-icon>
          <span>答疑 / 作业批改</span>
        </el-menu-item>
        <el-menu-item index="/student/photo-search">
          <el-icon><Camera /></el-icon>
          <span>拍照搜题</span>
        </el-menu-item>
        <el-menu-item index="/student/wrong-book">
          <el-icon><Notebook /></el-icon>
          <span>错题集</span>
        </el-menu-item>
        <el-menu-item index="/student/knowledge-graph">
          <el-icon><Share /></el-icon>
          <span>知识图谱</span>
        </el-menu-item>
      </el-menu>

      <!-- 历史会话（侧栏内展开） -->
      <div class="conv-panel" :class="{ expanded: convExpanded }">
        <button class="conv-toggle" @click="convExpanded = !convExpanded">
          <el-icon :size="18"><ChatDotRound /></el-icon>
          <span>历史会话</span>
          <el-icon :size="14" class="conv-arrow" :class="{ rotated: convExpanded }"><ArrowDown /></el-icon>
        </button>
        <div v-show="convExpanded" class="conv-list">
          <div v-if="loadingConvs" class="conv-loading">
            <span class="conv-dot"></span><span class="conv-dot"></span><span class="conv-dot"></span>
          </div>
          <div v-else-if="!convs.length" class="conv-empty">暂无历史会话</div>
          <div
            v-else
            v-for="c in convs"
            :key="c.id"
            class="conv-item"
            :class="{ pinned: c.is_pinned }"
            @click="openConv(c.id)"
          >
            <div class="conv-item-top">
              <el-icon v-if="c.is_pinned" :size="10" class="conv-pin"><Top /></el-icon>
              <span class="conv-title">{{ c.title || '新对话' }}</span>
            </div>
            <div class="conv-item-meta">
              <span>{{ fmtConvTime(c.updated_at || c.created_at) }}</span>
              <span v-if="c.message_count">{{ c.message_count }}条</span>
            </div>
            <div class="conv-item-acts" @click.stop>
              <button class="conv-act" title="置顶" @click="togglePin(c.id, c)"><el-icon :size="11"><Top /></el-icon></button>
              <button class="conv-act conv-act-del" title="删除" @click="delConv(c.id)"><el-icon :size="11"><Delete /></el-icon></button>
            </div>
          </div>
        </div>
      </div>

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
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Sunny, Moon, ChatLineSquare, Camera, Notebook, Share, SwitchButton, ChatDotRound, ArrowDown, Top, Delete
} from '@element-plus/icons-vue'
import { getChatHistory, pinConversation, deleteConversation } from '@/api/index'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { isDark, toggle } = useTheme()

// --- 历史会话面板 ---
const convExpanded = ref(false)
const convs = ref([])
const loadingConvs = ref(false)

async function loadConvs() {
  loadingConvs.value = true
  try {
    const res = await getChatHistory(50)
    convs.value = res.conversations || []
  } catch (_) { /* skip */ }
  finally { loadingConvs.value = false }
}

function openConv(id) {
  router.push({ path: '/student/home', query: { conversation_id: id } })
}

async function togglePin(id, conv) {
  try {
    const res = await pinConversation(id)
    conv.is_pinned = res.is_pinned ? 1 : 0
    ElMessage.success(res.message)
    await loadConvs()
  } catch (_) { ElMessage.error('操作失败') }
}

async function delConv(id) {
  try {
    await ElMessageBox.confirm('确定删除该对话？', '提示', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await deleteConversation(id)
    ElMessage.success('已删除')
    await loadConvs()
  } catch (_) { /* cancelled */ }
}

function fmtConvTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const now = new Date()
  const diffMin = Math.floor((now - d) / 60000)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffHour < 24) return `${diffHour}小时前`
  if (diffDay < 7) return `${diffDay}天前`
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}-${day}`
}

function handleLogout() {
  authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

onMounted(() => { loadConvs() })
</script>

<style scoped>
/* ================================================================
   StudentLayout — 深空渐变侧栏（与管理员端共享设计语言）
   设计：深空渐变 + 星光粒子 + 玻璃态导航项 + 蓝紫激活指示
   所有交互 0.28s cubic-bezier(0.4, 0, 0.2, 1)
   ================================================================ */

/* ----- 侧栏基础 ----- */
.student-sidebar {
  background: linear-gradient(172deg, #090B1A 0%, #0F1133 35%, #0B0D24 65%, #080A1D 100%) !important;
  border-right: 1px solid rgba(255, 255, 255, 0.04);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* 星光光晕 */
.student-sidebar::before {
  content: '';
  position: absolute;
  top: 8%; right: 12%;
  width: 180px; height: 180px;
  border-radius: 50%;
  background: radial-gradient(circle at 60% 40%,
    rgba(75, 94, 228, 0.08) 0%,
    rgba(124, 111, 240, 0.04) 35%,
    transparent 70%);
  pointer-events: none;
}
.student-sidebar::after {
  content: '';
  position: absolute;
  bottom: 10%; left: 8%;
  width: 120px; height: 120px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 70%,
    rgba(212, 155, 58, 0.05) 0%,
    rgba(212, 155, 58, 0.02) 50%,
    transparent 70%);
  pointer-events: none;
}

/* 星星粒子 */
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
.sidebar-stars span:nth-child(1) { top: 14%; left: 20%; animation-delay: 0s; }
.sidebar-stars span:nth-child(2) { top: 32%; left: 72%; animation-delay: 0.8s; width: 1.5px; height: 1.5px; }
.sidebar-stars span:nth-child(3) { top: 48%; left: 12%; animation-delay: 1.6s; }
.sidebar-stars span:nth-child(4) { top: 64%; left: 80%; animation-delay: 2.4s; width: 1.5px; height: 1.5px; }
.sidebar-stars span:nth-child(5) { top: 78%; left: 24%; animation-delay: 0.4s; }
.sidebar-stars span:nth-child(6) { top: 10%; left: 58%; animation-delay: 2.0s; width: 1px; height: 1px; }
.sidebar-stars span:nth-child(7) { top: 68%; left: 46%; animation-delay: 1.2s; width: 1px; height: 1px; }
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
  flex: 0 0 auto;
  border-right: none !important;
  padding: var(--space-3) var(--space-2) 0;
  overflow: visible;
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
/* 激活态蓝紫渐变指示线 */
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

/* ----- 历史会话面板（侧栏内展开） ----- */
.conv-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  z-index: 1;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.conv-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: calc(100% - 12px);
  height: 42px;
  margin: 2px 6px;
  padding: 0 16px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  font-family: var(--font-family-base);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  letter-spacing: 0.01em;
}
.conv-toggle:hover {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.9);
}
.conv-panel.expanded .conv-toggle {
  color: rgba(255, 255, 255, 0.9);
  background: rgba(75, 94, 228, 0.1);
  box-shadow: 0 0 0 1px rgba(75, 94, 228, 0.15);
}
.conv-arrow {
  margin-left: auto;
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  font-size: 12px;
}
.conv-arrow.rotated {
  transform: rotate(180deg);
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 var(--space-2) var(--space-3);
}
.conv-list::-webkit-scrollbar { width: 3px; }
.conv-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 10px;
}

.conv-loading {
  display: flex;
  justify-content: center;
  gap: 4px;
  padding: var(--space-4) 0;
}
.conv-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  animation: conv-dot-pulse 1.2s infinite;
}
.conv-dot:nth-child(2) { animation-delay: 0.2s; }
.conv-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes conv-dot-pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1.1); }
}
.conv-empty {
  text-align: center;
  padding: var(--space-4) 0;
  font-size: var(--text-xs);
  color: rgba(255, 255, 255, 0.25);
}

.conv-item {
  padding: var(--space-2) var(--space-3);
  margin: 2px 0;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  border-left: 2px solid transparent;
}
.conv-item:hover {
  background: rgba(255, 255, 255, 0.05);
}
.conv-item.pinned {
  border-left-color: rgba(245, 158, 11, 0.5);
  background: rgba(245, 158, 11, 0.04);
}
.conv-item-top {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 2px;
}
.conv-pin { color: #f59e0b; flex-shrink: 0; }
.conv-title {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: rgba(255, 255, 255, 0.7);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.4;
}
.conv-item-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 11px;
  color: rgba(255, 255, 255, 0.25);
  padding-left: 14px;
}
.conv-item-acts {
  display: none;
  position: absolute;
  right: 4px;
  top: 4px;
  gap: 2px;
}
.conv-item:hover .conv-item-acts {
  display: flex;
}
.conv-act {
  width: 20px; height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: rgba(255, 255, 255, 0.3);
  cursor: pointer;
  transition: all 0.15s ease;
}
.conv-act:hover {
  color: rgba(245, 158, 11, 0.8);
  background: rgba(245, 158, 11, 0.1);
}
.conv-act-del:hover {
  color: rgba(255, 110, 110, 0.8);
  background: rgba(255, 110, 110, 0.1);
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
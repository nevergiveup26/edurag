<template>
  <!--
    HistoryView.vue — Material Design 3 对话历史页面
    展示学生用户的对话记录，支持分页、详情查看
  -->
  <div class="history-page">
    <!-- 页面头部 -->
    <div class="history-header">
      <div class="header-left">
        <h2 class="page-title">
          <el-icon :size="20"><Clock /></el-icon>
          对话历史
        </h2>
        <el-tag type="info" effect="plain" size="small" class="count-tag">共 {{ total }} 条</el-tag>
      </div>
      <button class="new-chat-btn" @click="$router.push('/student/home')">
        <el-icon :size="16"><Plus /></el-icon>
        <span>新对话</span>
      </button>
    </div>

    <!-- 表格区域 -->
    <div class="table-card">
      <el-table
        :data="conversations"
        v-loading="loading"
        empty-text="暂无对话记录"
        stripe
        class="history-table"
        @row-click="openConversation"
      >
        <!-- ID 列 -->
        <el-table-column prop="id" label="ID" width="90" align="center">
          <template #default="{ row }">
            <code class="id-code">{{ row.id?.slice(0, 8) }}</code>
          </template>
        </el-table-column>

        <!-- 标题列 -->
        <el-table-column prop="title" label="对话标题" min-width="220">
          <template #default="{ row }">
            <div class="title-cell">
              <el-icon :size="16" class="title-icon"><ChatDotSquare /></el-icon>
              <span class="title-text">{{ row.title || '新对话' }}</span>
            </div>
          </template>
        </el-table-column>

        <!-- 消息数列 -->
        <el-table-column prop="message_count" label="消息数" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="info" effect="light" round>
              {{ row.message_count || 0 }} 条
            </el-tag>
          </template>
        </el-table-column>

        <!-- 创建时间列 -->
        <el-table-column prop="created_at" label="创建时间" width="180" align="center">
          <template #default="{ row }">
            <span class="time-text">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <!-- 操作列（图标按钮） -->
        <el-table-column label="操作" width="150" align="center" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <button class="action-btn action-view" title="查看详情" @click.stop="openConversation(row)">
                <el-icon :size="16"><View /></el-icon>
              </button>
              <button class="action-btn action-continue" title="继续聊天" @click.stop="continueChat(row)">
                <el-icon :size="16"><Promotion /></el-icon>
              </button>
              <button class="action-btn action-delete" title="删除" @click.stop="deleteConversationRow(row)">
                <el-icon :size="16"><Delete /></el-icon>
              </button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrap" v-if="total > pageSize">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="fetchList"
          background
          size="small"
          class="custom-pagination"
        />
      </div>
    </div>

    <!-- 对话详情弹窗 -->
    <el-drawer
      v-model="detailVisible"
      :title="detailTitle"
      size="560px"
      direction="rtl"
      class="detail-drawer"
    >
      <div v-if="detailLoading" class="loading-state">
        <span class="thinking-dot"></span>
        <span class="thinking-dot"></span>
        <span class="thinking-dot"></span>
      </div>
      <div v-else-if="detailMessages.length" class="detail-messages">
        <div v-for="(msg, i) in detailMessages" :key="i" class="detail-msg" :class="msg.role">
          <div class="detail-msg-header">
            <span class="detail-role-badge" :class="msg.role">
              {{ msg.role === 'user' ? '👤 我' : '🤖 AI' }}
            </span>
            <span class="detail-msg-time">{{ formatTime(msg.time || msg.created_at) }}</span>
          </div>
          <div class="detail-msg-body" v-html="renderMarkdown(msg.content)" />
        </div>
      </div>
      <div v-else-if="!detailLoading" class="empty-detail">
        <el-icon :size="36" color="#C9CDD4"><ChatLineSquare /></el-icon>
        <p>暂无消息内容</p>
      </div>
      <!-- 底部：继续聊天按钮 -->
      <div v-if="detailMessages.length && currentDetailId" class="drawer-footer">
        <el-button type="primary" :icon="Promotion" round @click="continueChatById">
          继续聊天
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
/**
 * HistoryView.vue — 对话历史页面逻辑
 * 展示学生对话记录，支持列表分页和详情查看
 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getConversations, getConversation, deleteConversation } from '@/api/index'
import { Clock, Plus, ChatDotSquare, View, Delete, ChatLineSquare, Promotion } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import hljs from 'highlight.js'
import katex from 'katex'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'
import 'katex/dist/katex.min.css'

marked.setOptions({
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value
    return hljs.highlightAuto(code).value
  },
})

function renderMarkdown(text) {
  if (!text) return ''
  let html = marked(text)
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: true, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  html = html.replace(/\$([^$]+?)\$/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: false, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  html = html.replace(/(\\left[(\[\\|.]|\\right[)\]\\|.]|\\frac\{[^}]+\}\{[^}]+\}|\\sqrt(\[\d+\])?\{[^}]+\}|\\times|\\div|\\pm|\\mp|\\cdot|\\leq|\\geq|\\neq|\\approx|\\sim|\\infty|\\pi|\\alpha|\\beta|\\gamma|\\delta|\\theta|\\lambda|\\mu|\\sigma|\\sum|\\int|\\prod|\\lim|\\to|\\rightarrow|\\Rightarrow|\\Leftrightarrow|\\angle|\\triangle|\\parallel|\\perp|\\circ|\\degree|\\%|\\qquad|\\quad|\\big|\\Big|\\bigg|\\Bigg|\\overline\{[^}]+\}|\\underline\{[^}]+\}|\\hat\{[^}]+\}|\\bar\{[^}]+\}|\\vec\{[^}]+\}|\\dot\{[^}]+\}|\\ddot\{[^}]+\}|\\text\{[^}]*\}|\\textbf\{[^}]*\}|\\textit\{[^}]*\})/g, (m) => { try { return katex.renderToString(m, { displayMode: false, throwOnError: false }) } catch { return m } })
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] })
}

function formatTime(t) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

// ---- 列表 ----
const loading = ref(false)
const conversations = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)

// ---- 详情 ----
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailMessages = ref([])
const detailTitle = ref('')
const currentDetailId = ref(null)

async function fetchList() {
  loading.value = true
  try {
    const res = await getConversations(page.value, pageSize.value)
    conversations.value = res.conversations || []
    total.value = res.total || 0
  } catch (_) {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

async function openConversation(row) {
  if (currentDetailId.value === row.id) {
    detailVisible.value = true
    return
  }
  currentDetailId.value = row.id
  detailTitle.value = row.title || '对话详情'
  detailVisible.value = true
  detailLoading.value = true
  detailMessages.value = []
  try {
    const res = await getConversation(row.id)
    detailMessages.value = res.messages || []
  } catch (_) {
    ElMessage.error('加载对话详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function deleteConversationRow(row) {
  try {
    await ElMessageBox.confirm('确定删除该对话吗？', '提示', { type: 'warning' })
    await deleteConversation(row.id)
    ElMessage.success('对话已删除')
    fetchList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

const router = useRouter()

function continueChat(row) {
  router.push({ path: '/student/home', query: { conversation_id: row.id } })
}

function continueChatById() {
  if (currentDetailId.value) {
    detailVisible.value = false
    router.push({ path: '/student/home', query: { conversation_id: currentDetailId.value } })
  }
}

onMounted(fetchList)
</script>

<style scoped>
/* ================================================================
   HistoryView.vue — MD3 对话历史页面样式
   设计要点：
   - 斑马纹表格 + 行悬停微高亮
   - 表头浅灰背景 + 底部边框
   - 图标按钮 + 悬停背景色
   - 分页组件按钮圆角优化
   - "新对话"按钮突出主色设计
   - 所有交互 0.25s ease-in-out
   ================================================================ */

.history-page { max-width: 1000px; margin: 0 auto; }

/* ----- 页面头部 ----- */
.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-5);
  flex-wrap: wrap;
  gap: var(--space-3);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.history-header .page-title {
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-primary);
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: none;
}
.history-header .page-title::after { display: none; }

.count-tag {
  font-weight: var(--font-medium);
}

/* "新对话" 突出按钮 */
.new-chat-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  padding: 0 var(--space-5);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), #4080FF);
  color: #fff;
  font-family: var(--font-family-base);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: all var(--transition-base);
  position: relative;
  overflow: hidden;
}
.new-chat-btn::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0) 100%);
  transform: translateX(-100%);
  transition: transform 0.6s ease;
}
.new-chat-btn:hover::after { transform: translateX(100%); }
.new-chat-btn:hover {
  box-shadow: 0 4px 16px rgba(22, 93, 255, 0.3);
  transform: translateY(-1px);
}
.new-chat-btn:active { transform: translateY(0); }

/* ----- 表格卡片 ----- */
.table-card {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

/* ----- 表格自定义 ----- */
.history-table {
  --el-table-border-color: var(--color-divider);
  --el-table-header-bg-color: var(--color-surface-secondary);
  --el-table-row-hover-bg-color: rgba(22, 93, 255, 0.03);
}

/* 表头样式 */
.history-table :deep(.el-table__header-wrapper th.el-table__cell) {
  background: var(--color-surface-secondary) !important;
  border-bottom: 2px solid var(--color-border) !important;
  font-weight: var(--font-semibold);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  letter-spacing: 0.3px;
  padding: var(--space-3) 0;
}

/* 斑马纹 */
.history-table :deep(.el-table__body-wrapper .el-table__row--striped td.el-table__cell) {
  background: var(--color-surface-secondary) !important;
}

/* 行悬停 */
.history-table :deep(.el-table__body-wrapper tr.el-table__row:hover > td.el-table__cell) {
  background: rgba(22, 93, 255, 0.04) !important;
}

/* 单元格内边距 */
.history-table :deep(td.el-table__cell) {
  padding: var(--space-3) 0;
}

/* 游标 */
.history-table :deep(.el-table__body-wrapper tr) {
  cursor: pointer;
}

/* --- 列样式 --- */
.id-code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--color-bg);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  color: var(--color-text-tertiary);
}

.title-cell {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.title-icon {
  color: var(--color-text-tertiary);
  flex-shrink: 0;
}
.title-text {
  font-weight: var(--font-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
}

.time-text {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

/* 操作按钮 */
.action-btns {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
}

.action-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
  transition: all var(--transition-fast);
  color: var(--color-text-tertiary);
}
.action-view:hover {
  background: var(--color-primary-light);
  color: var(--color-primary);
}
.action-continue:hover {
  background: var(--color-success-light, #e8f5e9);
  color: var(--color-success, #4caf50);
}
.action-delete:hover {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

/* ----- 分页 ----- */
.pagination-wrap {
  display: flex;
  justify-content: center;
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-divider);
}

.custom-pagination {
  --el-pagination-button-bg-color: var(--color-bg);
  --el-pagination-hover-color: var(--color-primary);
}
.custom-pagination :deep(.el-pager li) {
  border-radius: var(--radius-md) !important;
  font-weight: var(--font-medium);
  transition: all var(--transition-base);
}
.custom-pagination :deep(.el-pager li.is-active) {
  background: var(--color-primary) !important;
  color: #fff !important;
  box-shadow: 0 2px 6px rgba(22, 93, 255, 0.25);
}
.custom-pagination :deep(.btn-prev),
.custom-pagination :deep(.btn-next) {
  border-radius: var(--radius-md) !important;
  background: var(--color-bg) !important;
  transition: all var(--transition-base);
}
.custom-pagination :deep(.btn-prev:hover:not(:disabled)),
.custom-pagination :deep(.btn-next:hover:not(:disabled)) {
  background: var(--color-primary-light) !important;
  color: var(--color-primary) !important;
}

/* ----- 详情弹窗 ----- */
.detail-drawer :deep(.el-drawer__header) {
  margin-bottom: 0;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-divider);
  font-weight: var(--font-semibold);
}
.detail-drawer :deep(.el-drawer__body) {
  padding: var(--space-4) var(--space-5);
}

.detail-msg {
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  animation: msg-in 0.3s var(--easing-emphasized);
}
@keyframes msg-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.detail-msg.user {
  background: var(--color-primary-light);
  border: 1px solid rgba(22, 93, 255, 0.1);
}
.detail-msg.assistant {
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
}
.detail-msg-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
}
.detail-role-badge {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
}
.detail-role-badge.user { color: var(--color-primary); }
.detail-role-badge.assistant { color: var(--color-success); }
.detail-msg-time {
  font-size: var(--text-xs);
  color: var(--color-text-disabled);
}
.detail-msg-body {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  color: var(--color-text-primary);
}
.detail-msg-body :deep(p) { margin: 6px 0; }
.detail-msg-body :deep(pre) {
  background: #1e1e1e; color: #d4d4d4;
  padding: 12px; border-radius: var(--radius-md);
  overflow-x: auto; margin: var(--space-2) 0;
  font-size: var(--text-sm);
}
.detail-msg-body :deep(code) {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

/* 加载与空状态 */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-12);
}
.thinking-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-primary);
  animation: dot-pulse 1.4s ease-in-out infinite;
}
.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1.2); }
}

.empty-detail {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-5);
  color: var(--color-text-tertiary);
  gap: var(--space-3);
}
.empty-detail p {
  font-size: var(--text-sm);
}

/* 底部继续聊天按钮 */
.drawer-footer {
  position: sticky;
  bottom: 0;
  padding: var(--space-4);
  background: var(--color-bg-page, #f5f7fa);
  border-top: 1px solid var(--color-divider);
  display: flex;
  justify-content: center;
}

/* 暗黑模式 */
html.dark .table-card { background: var(--color-surface); border-color: var(--color-border); }
html.dark .history-table {
  --el-table-header-bg-color: var(--color-surface-secondary);
  --el-table-row-hover-bg-color: rgba(22, 93, 255, 0.08);
}
html.dark .history-table :deep(.el-table__body-wrapper .el-table__row--striped td.el-table__cell) {
  background: var(--color-surface-secondary) !important;
}
html.dark .id-code { background: var(--color-surface-secondary); }
html.dark .detail-msg.user { background: rgba(22, 93, 255, 0.08); }
html.dark .detail-msg.assistant { background: var(--color-surface-secondary); }
html.dark .custom-pagination :deep(.btn-prev),
html.dark .custom-pagination :deep(.btn-next) {
  background: var(--color-surface-secondary) !important;
}
</style>
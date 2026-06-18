<template>
  <!--
    ChatSidebar.vue — 豆包风格对话侧边栏
    滚动历史列表 + 置顶 + 新对话 + 删除
  -->
  <div class="chat-sidebar" :class="{ collapsed: !visible }">
    <!-- 新对话按钮 -->
    <div class="sidebar-header">
      <button class="new-chat-btn" @click="$emit('new-chat')">
        <el-icon :size="18"><Plus /></el-icon>
        <span>新对话</span>
      </button>
    </div>

    <!-- 对话列表 -->
    <div class="conversation-list" ref="listRef">
      <div
        v-for="(conv, idx) in conversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: conv.id === activeId, pinned: conv.is_pinned }"
        @click="$emit('select', conv.id)"
      >
        <div class="conv-content">
          <div class="conv-title">
            <el-icon v-if="conv.is_pinned" :size="12" class="pin-icon"><Top /></el-icon>
            <span class="title-text">{{ conv.title || '新对话' }}</span>
          </div>
          <div class="conv-meta">
            <span class="conv-time">{{ formatTime(conv.updated_at || conv.created_at) }}</span>
            <span v-if="conv.message_count" class="conv-msg-count">{{ conv.message_count }} 条</span>
          </div>
        </div>
        <div class="conv-actions" @click.stop>
          <button class="act-btn pin-btn" :title="conv.is_pinned ? '取消置顶' : '置顶'" @click="$emit('pin', conv.id, conv)">
            <el-icon :size="14"><Top /></el-icon>
          </button>
          <button class="act-btn delete-btn" title="删除" @click="handleDelete(conv.id)">
            <el-icon :size="14"><Delete /></el-icon>
          </button>
        </div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="sidebar-loading">
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Top, Delete } from '@element-plus/icons-vue'

const props = defineProps({
  conversations: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  visible: { type: Boolean, default: true },
})

const emit = defineEmits(['select', 'new-chat', 'pin', 'delete', 'toggle'])

const listRef = ref(null)

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const now = new Date()
  const diffMs = now - d
  const diffMin = Math.floor(diffMs / 60000)
  const diffHour = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)

  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffHour < 24) return `${diffHour}小时前`
  if (diffDay < 7) return `${diffDay}天前`

  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  if (y === now.getFullYear()) return `${m}-${day} ${h}:${min}`
  return `${y}-${m}-${day}`
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除该对话？', '提示', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    emit('delete', id)
  } catch {
    // cancelled
  }
}
</script>

<style scoped>
.chat-sidebar {
  width: 280px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
  border-right: 1px solid var(--color-border);
  flex-shrink: 0;
  overflow: hidden;
  transition: width 0.28s var(--easing-emphasized, cubic-bezier(0.4, 0, 0.2, 1));
}
.chat-sidebar.collapsed {
  width: 0;
  border-right: none;
}

/* 头部 */
.sidebar-header {
  padding: var(--space-3);
  flex-shrink: 0;
  border-bottom: 1px solid var(--color-divider);
}
.new-chat-btn {
  width: 100%;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), #4080FF);
  color: #fff;
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: all 0.2s ease;
}
.new-chat-btn:hover {
  box-shadow: 0 2px 10px rgba(22, 93, 255, 0.3);
  transform: translateY(-1px);
}
.new-chat-btn:active { transform: translateY(0); }

/* 对话列表 */
.conversation-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--space-1) 0;
}
.conversation-list::-webkit-scrollbar { width: 3px; }
.conversation-list::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 10px;
}

.conv-item {
  display: flex;
  align-items: flex-start;
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.2s ease;
  position: relative;
  gap: var(--space-2);
}
.conv-item:hover {
  background: var(--color-surface-secondary);
}
.conv-item.active {
  background: var(--color-primary-light, rgba(22, 93, 255, 0.06));
  border-left-color: var(--color-primary);
}
.conv-item.pinned {
  background: rgba(255, 193, 7, 0.03);
}

.conv-content {
  flex: 1;
  min-width: 0;
}
.conv-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-text-primary);
  line-height: 1.4;
  margin-bottom: 2px;
}
.conv-title .title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pin-icon {
  color: #f59e0b;
  flex-shrink: 0;
}
.conv-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.conv-msg-count {
  color: var(--color-text-quaternary, #aaa);
}

/* 操作按钮（悬停显示） */
.conv-actions {
  display: none;
  gap: 2px;
  flex-shrink: 0;
  align-items: center;
  margin-top: 1px;
}
.conv-item:hover .conv-actions {
  display: flex;
}
.act-btn {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  color: var(--color-text-tertiary);
  transition: all 0.15s ease;
}
.act-btn:hover {
  background: var(--color-surface-tertiary, rgba(0,0,0,0.04));
}
.pin-btn:hover {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.1);
}
.delete-btn:hover {
  color: var(--color-danger);
  background: var(--color-danger-light);
}

/* 加载动画 */
.sidebar-loading {
  display: flex;
  justify-content: center;
  gap: 4px;
  padding: var(--space-4);
}
.loading-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--color-text-tertiary);
  animation: dot-pulse 1.2s infinite;
}
.loading-dot:nth-child(2) { animation-delay: 0.2s; }
.loading-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.9); }
  40% { opacity: 1; transform: scale(1.1); }
}
</style>

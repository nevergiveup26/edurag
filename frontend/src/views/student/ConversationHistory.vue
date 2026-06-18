<template>
  <div class="conv-page">
    <div class="page-title">
      <el-icon :size="20"><ChatDotRound /></el-icon>
      <span>历史会话</span>
      <button class="outline-btn-sm" style="margin-left:auto;" @click="newChat">
        <el-icon :size="14"><Plus /></el-icon> 新对话
      </button>
    </div>

    <div v-if="loading" class="conv-loading">
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
    </div>

    <el-empty v-else-if="!list.length" description="暂无历史会话" :image-size="100" />

    <div v-else class="conv-list">
      <div
        v-for="conv in list"
        :key="conv.id"
        class="conv-card surface-card"
        :class="{ pinned: conv.is_pinned }"
        @click="openConv(conv.id)"
      >
        <div class="conv-card-body">
          <div class="conv-card-left">
            <el-icon v-if="conv.is_pinned" :size="14" class="conv-pin-icon"><Top /></el-icon>
            <div class="conv-card-main">
              <div class="conv-card-title">{{ conv.title || '新对话' }}</div>
              <div class="conv-card-meta">
                <span>{{ formatTime(conv.updated_at || conv.created_at) }}</span>
                <span v-if="conv.message_count">{{ conv.message_count }} 条消息</span>
              </div>
            </div>
          </div>
          <div class="conv-card-actions" @click.stop>
            <button class="text-btn" @click="togglePin(conv.id, conv)">
              {{ conv.is_pinned ? '取消置顶' : '置顶' }}
            </button>
            <button class="text-btn" style="color:var(--color-danger);" @click="handleDelete(conv.id)">
              删除
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getChatHistory, pinConversation, deleteConversation, createConversation } from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Plus, Top } from '@element-plus/icons-vue'

const router = useRouter()
const list = ref([])
const loading = ref(false)

async function loadList() {
  loading.value = true
  try {
    const res = await getChatHistory(100)
    list.value = res.conversations || []
  } catch (_) { /* skip */ }
  finally { loading.value = false }
}

function openConv(id) {
  router.push({ path: '/student/home', query: { conversation_id: id } })
}

async function newChat() {
  try {
    const res = await createConversation()
    router.push({ path: '/student/home', query: { conversation_id: res.conversation_id } })
  } catch (_) {
    router.push('/student/home')
  }
}

async function togglePin(id, conv) {
  try {
    const res = await pinConversation(id)
    conv.is_pinned = res.is_pinned ? 1 : 0
    ElMessage.success(res.message)
    await loadList()
  } catch (_) {
    ElMessage.error('操作失败')
  }
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除该对话？', '提示', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await deleteConversation(id)
    ElMessage.success('对话已删除')
    await loadList()
  } catch (_) { /* cancelled */ }
}

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

onMounted(() => { loadList() })
</script>

<style scoped>
.conv-page { max-width: 800px; margin: 0 auto; }

.conv-loading {
  display: flex;
  justify-content: center;
  gap: 4px;
  padding: var(--space-10);
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

.conv-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.conv-card {
  cursor: pointer;
  transition: all 0.2s ease;
}
.conv-card:hover {
  border-color: var(--color-primary);
  transform: translateX(4px);
}
.conv-card.pinned {
  border-left: 3px solid #f59e0b;
}

.conv-card-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  gap: var(--space-3);
}
.conv-card-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
}
.conv-pin-icon { color: #f59e0b; flex-shrink: 0; }
.conv-card-main { min-width: 0; }
.conv-card-title {
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}
.conv-card-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.conv-card-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.conv-card:hover .conv-card-actions { opacity: 1; }
</style>

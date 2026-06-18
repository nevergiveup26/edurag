<template>
  <!--
    TracesView.vue — 管理端调用链追踪（MD3 灵动风格）
    追踪列表表格 + 详情弹窗（Descriptions + Timeline + 检索结果）
  -->
  <div class="traces-page">
    <h2 class="page-title"><el-icon :size="22"><Connection /></el-icon> 调用链追踪</h2>

    <!-- ===== 追踪列表 ===== -->
    <div class="surface-card">
      <div class="card-header">
        <span class="card-title">🔍 最近调用记录</span>
        <button class="icon-btn" title="刷新" @click="loadTraces" :disabled="loading">
          <el-icon :size="16" :class="{ 'is-loading': loading }"><Refresh /></el-icon>
        </button>
      </div>
      <el-table :data="traces" stripe v-loading="loading" empty-text="暂无调用记录" size="small" class="styled-table">
        <el-table-column prop="trace_id" label="Trace ID" width="170" show-overflow-tooltip>
          <template #default="{row}"><code class="id-code">{{ row.trace_id?.slice(0,10) }}</code></template>
        </el-table-column>
        <el-table-column prop="query" label="查询内容" min-width="220" show-overflow-tooltip>
          <template #default="{row}">{{ (row.query || '').slice(0, 80) }}</template>
        </el-table-column>
        <el-table-column prop="strategy" label="策略" width="100" align="center">
          <template #default="{row}">
            <el-tag size="small" type="info" effect="light" round>{{ row.strategy || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="duration_ms" label="耗时" width="100" align="center">
          <template #default="{row}">
            <el-tag size="small" :type="row.duration_ms > 3000 ? 'danger' : row.duration_ms > 1000 ? 'warning' : 'success'" effect="light">
              {{ row.duration_ms ? row.duration_ms + 'ms' : '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80" align="center">
          <template #default="{row}">
            <el-tag size="small" :type="row.status === 'success' ? 'success' : 'danger'" effect="light" round>
              {{ row.status || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="timestamp" label="时间" width="170" align="center">
          <template #default="{row}">{{ formatTime(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center" fixed="right">
          <template #default="{row}">
            <button class="action-btn action-view" title="查看详情" @click="showDetail(row)">
              <el-icon :size="15"><View /></el-icon>
            </button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ===== 详情弹窗 ===== -->
    <el-dialog v-model="detailVisible" title="调用链详情" width="700px" destroy-on-close>
      <div v-if="detailLoading" class="loading-state">
        <span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>
      </div>
      <div v-else-if="traceDetail" class="trace-detail">
        <!-- 基本信息 -->
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="Trace ID">{{ traceDetail.trace_id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="traceDetail.status === 'success' ? 'success' : 'danger'">{{ traceDetail.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="查询">{{ traceDetail.query }}</el-descriptions-item>
          <el-descriptions-item label="策略">{{ traceDetail.strategy || '-' }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ traceDetail.duration_ms }}ms</el-descriptions-item>
          <el-descriptions-item label="Top-K">{{ traceDetail.top_k || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时间" :span="2">{{ formatTime(traceDetail.timestamp) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 执行步骤 -->
        <h4 class="section-title">⚙️ 执行步骤</h4>
        <el-timeline v-if="traceDetail.steps?.length">
          <el-timeline-item
            v-for="(step, i) in traceDetail.steps" :key="i"
            :timestamp="step.duration_ms ? step.duration_ms + 'ms' : ''"
            :type="step.status === 'error' ? 'danger' : 'primary'"
            placement="top"
          >
            <strong>{{ step.name || 'Step ' + (i + 1) }}</strong>
            <p v-if="step.description" class="step-desc">{{ step.description }}</p>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="无步骤详情" :image-size="60" />

        <!-- 检索结果 -->
        <h4 class="section-title">📎 检索结果</h4>
        <div v-if="traceDetail.retrieved_chunks?.length">
          <div v-for="(chunk, i) in traceDetail.retrieved_chunks" :key="i" class="chunk-item">
            <el-tag size="small" type="primary" effect="light" class="chunk-score">
              {{ (chunk.score * 100).toFixed(1) }}%
            </el-tag>
            <span>{{ (chunk.content || '').slice(0, 250) }}</span>
          </div>
        </div>
        <el-empty v-else description="无检索结果" :image-size="60" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getTraces, getTraceDetail } from '@/api/admin'
import { ElMessage } from 'element-plus'
import { Refresh, View, Connection } from '@element-plus/icons-vue'

const loading = ref(false)
const traces = ref([])
const detailVisible = ref(false)
const detailLoading = ref(false)
const traceDetail = ref(null)

function formatTime(t) { return t ? new Date(t).toLocaleString('zh-CN') : '-' }

async function loadTraces() {
  loading.value = true
  try { const res = await getTraces(50); traces.value = res.traces || [] } catch (_) {} finally { loading.value = false }
}

async function showDetail(row) {
  detailVisible.value = true; detailLoading.value = true; traceDetail.value = null
  try { traceDetail.value = await getTraceDetail(row.trace_id) } catch (_) { ElMessage.error('加载详情失败') } finally { detailLoading.value = false }
}

onMounted(loadTraces)
</script>

<style scoped>
.traces-page { max-width: 1200px; margin: 0 auto; }

/* 详情 */
.trace-detail { max-height: 500px; overflow-y: auto; }
.section-title { font-size: var(--text-base); font-weight: var(--font-semibold); margin: var(--space-5) 0 var(--space-3); color: var(--color-text-primary); }
.step-desc { font-size: var(--text-sm); color: var(--color-text-tertiary); margin-top: 4px; }
.chunk-item {
  padding: var(--space-2) var(--space-3); margin-bottom: var(--space-2);
  background: var(--color-bg); border-radius: var(--radius-md);
  border-left: 3px solid var(--color-primary); font-size: var(--text-sm); line-height: 1.6;
}
.chunk-score { margin-right: var(--space-2); }
.loading-state { display: flex; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-10); }
.thinking-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--color-primary); animation: dot-pulse 1.4s ease-in-out infinite;
}
.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1.2); }
}
</style>
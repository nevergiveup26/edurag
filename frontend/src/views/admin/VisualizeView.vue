<template>
  <!--
    VisualizeView.vue — 检索可视化 + 调用链追踪（合并）
    统计卡片 → 检索演示 → 实时调用链 → 历史追踪列表
  -->
  <div class="viz-page">
    <div class="page-header">
      <h2 class="page-title"><el-icon :size="22"><DataAnalysis /></el-icon> 检索可视化 & 调用链</h2>
    </div>

    <!-- ===== 1. 统计卡片 ===== -->
    <div class="surface-card">
      <div class="card-header">
        <span class="card-title">📊 知识库统计</span>
        <button class="gradient-btn-sm" :disabled="loading" @click="loadStats">
          <el-icon :size="14" :class="{ 'is-loading': loading }"><Refresh /></el-icon>
          刷新数据
        </button>
      </div>
      <div v-if="stats" class="stat-grid">
        <div class="stat-card" v-for="s in statCards" :key="s.label">
          <div class="stat-val" :style="{ color: s.color }">{{ s.value }}</div>
          <div class="stat-lbl">{{ s.label }}</div>
        </div>
      </div>
      <el-empty v-else description="暂无统计数据，请先上传文档" :image-size="120" />
    </div>

    <!-- ===== 2. 检索演示 ===== -->
    <div class="surface-card" style="margin-top: var(--space-5)">
      <div class="card-header"><span class="card-title">🔍 检索演示</span></div>
      <div class="search-area">
        <el-input
          v-model="query" placeholder="输入查询文本，查看检索效果与调用链..."
          @keyup.enter="doSearch" size="large" clearable class="search-input"
        >
          <template #append>
            <el-button :icon="Search" @click="doSearch" :loading="searching" type="primary">检索</el-button>
          </template>
        </el-input>
      </div>

      <!-- 检索结果 -->
      <div v-if="results.length" class="results-area">
        <h4 class="section-title">检索结果 (Top-{{ results.length }})</h4>
        <div v-for="(r, i) in results" :key="i" class="result-item">
          <div class="result-header">
            <el-tag size="small" type="primary" effect="light" round>
              {{ (r.score * 100).toFixed(1) }}%
            </el-tag>
            <span v-if="r.metadata?.source" class="result-source">📄 {{ r.metadata.source }}</span>
          </div>
          <p class="result-text">{{ (r.content || r.text || '').slice(0, 300) }}</p>
        </div>
      </div>
      <el-empty v-else-if="searched && !searching" description="未检索到相关结果" :image-size="80" style="padding:var(--space-8);" />

      <!-- ===== 3. 实时调用链 Timeline ===== -->
      <div v-if="currentTrace" class="trace-inline">
        <div class="trace-header">
          <h4 class="section-title">⚡ 本次调用链</h4>
          <el-tag size="small" :type="currentTrace.status === 'success' ? 'success' : 'danger'" effect="light" round>
            {{ currentTrace.status }}
          </el-tag>
        </div>
        <div class="trace-meta">
          <span>策略: <code>{{ currentTrace.strategy }}</code></span>
          <span>总耗时: <code>{{ currentTrace.duration_ms }}ms</code></span>
          <span>Top-K: <code>{{ currentTrace.top_k }}</code></span>
        </div>

        <!-- Timeline -->
        <el-timeline v-if="currentTrace.steps?.length">
          <el-timeline-item
            v-for="(step, i) in currentTrace.steps" :key="i"
            :timestamp="step.duration_ms != null ? step.duration_ms + 'ms' : ''"
            :type="step.status === 'error' ? 'danger' : 'primary'"
            placement="top"
            :hollow="step.status === 'error'"
          >
            <strong>{{ step.name }}</strong>
            <p v-if="step.description" class="step-desc">{{ step.description }}</p>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无步骤详情" :image-size="60" />

        <!-- 检索到的 chunks -->
        <div v-if="currentTrace.retrieved_chunks?.length" style="margin-top: var(--space-4);">
          <h4 class="section-title">📎 检索到的文档片段</h4>
          <div v-for="(chunk, i) in currentTrace.retrieved_chunks" :key="i" class="chunk-item">
            <el-tag size="small" type="primary" effect="light" class="chunk-score">
              {{ (chunk.score * 100).toFixed(1) }}%
            </el-tag>
            <span>{{ (chunk.content || '').slice(0, 250) }}</span>
          </div>
        </div>

        <!-- Langfuse 链接 -->
        <div v-if="currentTrace.langfuse_url" style="margin-top: var(--space-4); text-align: right;">
          <a :href="currentTrace.langfuse_url" target="_blank" class="langfuse-link">
            <el-icon :size="14"><Link /></el-icon> 在 Langfuse 中查看完整追踪
          </a>
        </div>
      </div>

      <!-- 加载中 -->
      <div v-if="searching" class="loading-state">
        <span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>
        <span style="margin-left: var(--space-3); color: var(--color-text-tertiary);">检索中...</span>
      </div>
    </div>

    <!-- ===== 4. 历史追踪列表 ===== -->
    <div class="surface-card" style="margin-top: var(--space-5)">
      <div class="card-header">
        <span class="card-title">📋 历史调用记录</span>
        <button class="icon-btn" title="刷新" @click="loadTraces" :disabled="traceLoading">
          <el-icon :size="16" :class="{ 'is-loading': traceLoading }"><Refresh /></el-icon>
        </button>
      </div>
      <el-table :data="traces" stripe v-loading="traceLoading" empty-text="暂无调用记录" size="small" class="styled-table">
        <el-table-column prop="trace_id" label="Trace ID" width="130" show-overflow-tooltip>
          <template #default="{row}"><code class="id-code">{{ row.trace_id?.slice(0,10) }}</code></template>
        </el-table-column>
        <el-table-column prop="query" label="查询内容" min-width="200" show-overflow-tooltip>
          <template #default="{row}">{{ (row.query || '').slice(0, 80) }}</template>
        </el-table-column>
        <el-table-column prop="strategy" label="策略" width="90" align="center">
          <template #default="{row}">
            <el-tag size="small" type="info" effect="light" round>{{ row.strategy || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="duration_ms" label="耗时" width="90" align="center">
          <template #default="{row}">
            <el-tag size="small" :type="row.duration_ms > 3000 ? 'danger' : row.duration_ms > 1000 ? 'warning' : 'success'" effect="light">
              {{ row.duration_ms ? row.duration_ms + 'ms' : '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="70" align="center">
          <template #default="{row}">
            <el-tag size="small" :type="row.status === 'success' ? 'success' : 'danger'" effect="light" round>
              {{ row.status || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="timestamp" label="时间" width="160" align="center">
          <template #default="{row}">{{ formatTime(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="70" align="center" fixed="right">
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

        <h4 class="section-title">⚙️ 执行步骤</h4>
        <el-timeline v-if="traceDetail.steps?.length">
          <el-timeline-item
            v-for="(step, i) in traceDetail.steps" :key="i"
            :timestamp="step.duration_ms != null ? step.duration_ms + 'ms' : ''"
            :type="step.status === 'error' ? 'danger' : 'primary'"
            placement="top"
          >
            <strong>{{ step.name || 'Step ' + (i + 1) }}</strong>
            <p v-if="step.description" class="step-desc">{{ step.description }}</p>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="无步骤详情" :image-size="60" />

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

        <div v-if="traceDetail.langfuse_url" style="margin-top: var(--space-5); text-align: right;">
          <a :href="traceDetail.langfuse_url" target="_blank" class="langfuse-link">
            <el-icon :size="14"><Link /></el-icon> 在 Langfuse 中查看
          </a>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { getStats, query as apiQuery } from '@/api/index'
import { getTraces, getTraceDetail } from '@/api/admin'
import { ElMessage } from 'element-plus'
import { Search, Refresh, View, Link, DataAnalysis } from '@element-plus/icons-vue'

const loading = ref(false)
const searching = ref(false)
const searched = ref(false)
const stats = ref(null)
const query = ref('')
const results = ref([])
const currentTrace = ref(null)  // 本次检索的实时调用链
const traces = ref([])
const traceLoading = ref(false)
const detailVisible = ref(false)
const detailLoading = ref(false)
const traceDetail = ref(null)

const statCards = computed(() => [
  { label: '文档总数', value: stats.value?.total_documents || 0, color: '#165DFF' },
  { label: '知识块数', value: stats.value?.total_chunks || 0, color: '#00B42A' },
  { label: '已索引文档', value: stats.value?.indexed_documents || 0, color: '#FF7D00' },
  { label: '平均块大小', value: stats.value?.avg_chunk_size || '-', color: '#F53F3F' },
])

function formatTime(t) { return t ? new Date(t).toLocaleString('zh-CN') : '-' }

async function loadStats() {
  loading.value = true
  try { stats.value = await getStats() } catch (_) {} finally { loading.value = false }
}

async function doSearch() {
  if (!query.value.trim()) return
  searching.value = true; searched.value = true; currentTrace.value = null
  try {
    const res = await apiQuery({ query: query.value.trim(), top_k: 5 })
    results.value = (res.sources || res.results || []).slice(0, 5)

    // 获取本次查询的实时调用链
    await fetchLatestTrace()
  } catch (_) { ElMessage.error('检索失败') } finally { searching.value = false }
}

async function fetchLatestTrace() {
  try {
    const res = await getTraces(1)
    if (res.traces?.length) {
      const latest = res.traces[0]
      currentTrace.value = await getTraceDetail(latest.trace_id)
    }
  } catch (_) { /* trace 获取失败不阻塞检索 */ }
}

async function loadTraces() {
  traceLoading.value = true
  try { const res = await getTraces(50); traces.value = res.traces || [] } catch (_) {} finally { traceLoading.value = false }
}

async function showDetail(row) {
  detailVisible.value = true; detailLoading.value = true; traceDetail.value = null
  try { traceDetail.value = await getTraceDetail(row.trace_id) } catch (_) { ElMessage.error('加载详情失败') } finally { detailLoading.value = false }
}

loadStats()
loadTraces()
</script>

<style scoped>
.viz-page { max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-5); }

/* 统计卡片 */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--space-4); padding: var(--space-4) var(--space-5) var(--space-5); }
.stat-card {
  text-align: center; padding: var(--space-5);
  background: var(--color-bg); border-radius: var(--radius-lg);
  border: 1px solid var(--color-border); transition: all var(--transition-base);
}
.stat-card:hover { background: var(--color-surface); box-shadow: var(--shadow-floating); transform: translateY(-1px); }
.stat-val { font-size: 28px; font-weight: var(--font-extrabold); line-height: 1.1; }
.stat-lbl { font-size: var(--text-sm); color: var(--color-text-tertiary); font-weight: var(--font-medium); margin-top: 4px; }

/* 检索 */
.search-area { padding: var(--space-4) var(--space-5); }
.results-area { padding: 0 var(--space-5); }
.section-title { font-size: var(--text-base); font-weight: var(--font-semibold); margin: var(--space-5) 0 var(--space-3); color: var(--color-text-primary); }
.result-item {
  padding: var(--space-3); margin-bottom: var(--space-2);
  background: var(--color-bg); border-radius: var(--radius-md);
  border-left: 3px solid var(--color-primary); transition: all var(--transition-base);
}
.result-item:hover { background: var(--color-primary-light); }
.result-header { display: flex; align-items: center; gap: var(--space-2); margin-bottom: 6px; }
.result-source { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.result-text { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); margin: 0; }

/* 实时调用链 */
.trace-inline {
  margin: var(--space-5); padding: var(--space-4);
  background: var(--color-bg); border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
}
.trace-header { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2); }
.trace-header .section-title { margin: 0; }
.trace-meta { display: flex; gap: var(--space-5); font-size: var(--text-sm); color: var(--color-text-tertiary); margin-bottom: var(--space-3); }
.trace-meta code { color: var(--color-primary); font-size: var(--text-sm); }

/* Timeline / 步骤 */
.step-desc { font-size: var(--text-sm); color: var(--color-text-tertiary); margin-top: 4px; }

/* 检索片段 */
.chunk-item {
  padding: var(--space-2) var(--space-3); margin-bottom: var(--space-2);
  background: var(--color-bg); border-radius: var(--radius-md);
  border-left: 3px solid var(--color-primary); font-size: var(--text-sm); line-height: 1.6;
}
.chunk-score { margin-right: var(--space-2); }

/* Langfuse 链接 */
.langfuse-link {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: var(--text-sm); color: var(--color-primary); text-decoration: none;
  font-weight: var(--font-medium); transition: opacity var(--transition-base);
}
.langfuse-link:hover { opacity: 0.8; }

/* 加载动画 */
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

/* 详情弹窗 */
.trace-detail { max-height: 60vh; overflow-y: auto; }

/* 表格样式 */
.id-code { font-size: 12px; color: var(--color-primary); background: var(--color-primary-light); padding: 2px 6px; border-radius: 4px; }
</style>

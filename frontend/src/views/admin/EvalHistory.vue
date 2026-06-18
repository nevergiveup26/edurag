<template>
  <!--
    EvalHistory.vue — 管理端评测历史（MD3 灵动风格）
    历史列表 + 对比选择 + 图表对比 + 详情抽屉
  -->
  <div class="evalhistory-page">
    <div class="page-header">
      <h2 class="page-title"><el-icon :size="22"><Timer /></el-icon> 评测历史</h2>
    </div>

    <!-- ===== 历史列表 ===== -->
    <div class="surface-card">
      <div class="card-header">
        <span class="card-title">📋 评测历史记录</span>
        <div class="header-actions">
          <el-tag v-if="compareMode.length" type="warning" effect="plain" size="small">
            已选 {{ compareMode.length }} 项
          </el-tag>
          <button
            v-if="compareMode.length >= 2"
            class="gradient-btn-sm" @click="doCompare"
          >
            <el-icon :size="14"><DataAnalysis /></el-icon> 对比
          </button>
          <button
            v-if="compareMode.length"
            class="outline-btn-sm" @click="compareMode = []"
          >
            <el-icon :size="14"><Close /></el-icon> 取消
          </button>
          <button class="icon-btn" title="刷新" @click="loadHistory" :disabled="loading">
            <el-icon :size="16" :class="{ 'is-loading': loading }"><Refresh /></el-icon>
          </button>
        </div>
      </div>

      <el-table
        :data="historyList" stripe v-loading="loading" empty-text="暂无评测记录"
        size="small" class="styled-table"
        @row-click="showHistoryDetail"
      >
        <el-table-column width="50" align="center">
          <template #default="{row}">
            <el-checkbox
              :model-value="compareMode.includes(row.id)"
              :disabled="compareMode.length >= 2 && !compareMode.includes(row.id)"
              @click.stop
              @change="(v) => toggleCompare(row.id, v)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="model_name" label="模型" width="130">
          <template #default="{row}">{{ row.model_name || (row.config?.model_name || '-') }}</template>
        </el-table-column>
        <el-table-column prop="evaluation_type" label="类型" width="100" align="center">
          <template #default="{row}">
            <el-tag size="small" :type="row.evaluation_type === 'ragas' ? 'success' : 'primary'" effect="light" round>
              {{ row.evaluation_type === 'ragas' ? 'RAGAS' : 'RAG' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="指标摘要" min-width="250">
          <template #default="{row}">
            <div class="metric-inline">
              <el-tag size="small" v-for="m in getMetrics(row)" :key="m.label" :type="m.type" effect="light">
                {{ m.label }}: {{ m.value }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="评测时间" width="180" align="center">
          <template #default="{row}">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center" fixed="right">
          <template #default="{row}">
            <button class="action-btn action-view" title="查看详情" @click.stop="showHistoryDetail(row)">
              <el-icon :size="15"><View /></el-icon>
            </button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ===== 对比结果 ===== -->
    <div v-if="compareResult" class="surface-card" style="margin-top: var(--space-5)">
      <div class="card-header">
        <span class="card-title">📊 对比结果</span>
        <button class="text-btn" @click="compareResult = null; compareMode = []">关闭</button>
      </div>
      <div class="compare-body">
        <el-table :data="compareResult.table" stripe size="small" border class="styled-table">
          <el-table-column prop="metric" label="指标" width="180" fixed />
          <el-table-column v-for="col in compareResult.models" :key="col" :label="col" align="center">
            <template #default="{row}">{{ row[col] || '-' }}</template>
          </el-table-column>
        </el-table>
        <div class="chart-row" v-if="compareResult.radar_chart">
          <img :src="'data:image/png;base64,' + compareResult.radar_chart" class="chart-img" />
        </div>
      </div>
    </div>

    <!-- ===== 详情抽屉 ===== -->
    <el-drawer v-model="detailVisible" title="评测详情" size="520px" direction="rtl">
      <div v-if="detailLoading" class="loading-state">
        <span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>
      </div>
      <div v-else-if="detail" class="history-detail">
        <!-- 模型信息 -->
        <div v-if="detail.config" class="detail-section">
          <h4 class="section-title">⚙️ 模型配置</h4>
          <div class="config-grid">
            <div class="config-item" v-if="detail.config.model_name">
              <span class="config-lbl">模型</span>
              <span class="config-val">{{ detail.config.model_name }}</span>
            </div>
            <div class="config-item" v-if="detail.config.embedding_model">
              <span class="config-lbl">Embedding</span>
              <span class="config-val">{{ detail.config.embedding_model }}</span>
            </div>
            <div class="config-item" v-if="detail.config.reranker_model">
              <span class="config-lbl">Reranker</span>
              <span class="config-val">{{ detail.config.reranker_model }}</span>
            </div>
            <div class="config-item" v-if="detail.config.evaluation_type">
              <span class="config-lbl">评测类型</span>
              <el-tag size="small" :type="detail.config.evaluation_type === 'ragas' ? 'success' : 'primary'" effect="light">
                {{ detail.config.evaluation_type === 'ragas' ? 'RAGAS' : 'RAG 检索' }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 指标 -->
        <div class="detail-section" v-if="detail.metrics">
          <h4 class="section-title">📊 评测指标</h4>
          <div class="metric-grid small">
            <div class="metric-card small" v-for="(v, k) in flattenMetrics(detail.metrics)" :key="k">
              <div class="metric-val small">{{ formatMetric(v) }}</div>
              <div class="metric-lbl">{{ k }}</div>
            </div>
          </div>
        </div>

        <!-- 图表 -->
        <div class="detail-section" v-if="detail.charts && Object.keys(detail.charts).length">
          <h4 class="section-title">📈 评测图表</h4>
          <img v-for="(chart, name) in detail.charts" :key="name"
               :src="'data:image/png;base64,' + chart" class="chart-img" />
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getEvalHistory, getEvalHistoryDetail, compareEvalHistory } from '@/api/admin'
import { ElMessage } from 'element-plus'
import { Timer, View, Close, Refresh, DataAnalysis } from '@element-plus/icons-vue'

const loading = ref(false)
const historyList = ref([])
const compareMode = ref([])
const compareResult = ref(null)
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)

function formatTime(t) { return t ? new Date(t).toLocaleString('zh-CN') : '-' }
function formatMetric(v) { if (v == null) return '-'; return typeof v === 'number' ? (v * 100).toFixed(1) + '%' : v }

function getMetrics(row) {
  const m = row.metrics || {}
  // 支持 retrieval 类型（嵌套在 .retrieval 和 .generation 中）
  const ret = m.retrieval || {}
  const gen = m.generation || {}
  const items = []
  if (m.precision != null || ret.precision != null) items.push({ label: 'P', value: (((m.precision ?? ret.precision)) * 100).toFixed(1) + '%', type: 'primary' })
  if (m.recall != null || ret.recall != null) items.push({ label: 'R', value: (((m.recall ?? ret.recall)) * 100).toFixed(1) + '%', type: 'success' })
  if (m.f1_score != null || ret.f1_score != null) items.push({ label: 'F1', value: (((m.f1_score ?? ret.f1_score)) * 100).toFixed(1) + '%', type: 'warning' })
  if (ret.hit_rate != null) items.push({ label: 'Hit', value: ((ret.hit_rate) * 100).toFixed(1) + '%', type: 'info' })
  if (ret.mrr != null) items.push({ label: 'MRR', value: ((ret.mrr) * 100).toFixed(1) + '%', type: 'info' })
  if (gen.keyword_match_rate != null) items.push({ label: 'KW', value: ((gen.keyword_match_rate) * 100).toFixed(1) + '%', type: 'warning' })
  if (m.faithfulness != null) items.push({ label: 'Faith', value: (m.faithfulness * 100).toFixed(1) + '%', type: 'success' })
  if (m.answer_relevancy != null) items.push({ label: 'Rel', value: (m.answer_relevancy * 100).toFixed(1) + '%', type: 'info' })
  if (m.context_relevancy != null) items.push({ label: 'CtxRel', value: (m.context_relevancy * 100).toFixed(1) + '%', type: 'warning' })
  return items
}

function flattenMetrics(m) {
  if (m.retrieval && m.generation) return { ...m.retrieval, ...m.generation }
  return m
}

function toggleCompare(id, val) {
  if (val) { if (compareMode.value.length < 2) compareMode.value.push(id) }
  else compareMode.value = compareMode.value.filter(x => x !== id)
}

async function loadHistory() {
  loading.value = true
  try { const res = await getEvalHistory(); historyList.value = res.history || [] } catch (_) {} finally { loading.value = false }
}

async function doCompare() {
  if (compareMode.value.length < 2) return
  try { compareResult.value = await compareEvalHistory(compareMode.value[0], compareMode.value[1]) } catch (_) {}
}

async function showHistoryDetail(row) {
  detailVisible.value = true; detailLoading.value = true; detail.value = null
  try { detail.value = await getEvalHistoryDetail(row.id) } catch (_) {} finally { detailLoading.value = false }
}

onMounted(loadHistory)
</script>

<style scoped>
.evalhistory-page { max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-5); }

.metric-inline { display: flex; flex-wrap: wrap; gap: 4px; }

/* 对比 */
.compare-body { padding: var(--space-4) var(--space-5); }
.chart-row { margin-top: var(--space-4); }
.chart-img { width: 100%; max-height: 350px; object-fit: contain; }

/* 详情 */
.history-detail { padding: 0; }
.detail-section { margin-bottom: var(--space-6); }
.section-title { font-size: var(--text-base); font-weight: var(--font-semibold); margin-bottom: var(--space-3); color: var(--color-text-primary); }
.config-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.config-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg); border-radius: var(--radius-md);
}
.config-lbl { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.config-val { font-size: var(--text-sm); font-weight: var(--font-medium); }

/* 指标小卡片 */
.metric-grid.small { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
.metric-card.small { padding: var(--space-3); }
.metric-val.small { font-size: 22px; }

.loading-state { display: flex; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-12); }
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
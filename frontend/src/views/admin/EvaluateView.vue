<template>
  <!--
    EvaluateView.vue — 管理端 RAG 评估（合并检索评测 + RAGAS 评测）
    Tab 切换 | 共用进度/日志 | 指标卡片动画 | 详情面板
  -->
  <div class="eval-page">
    <h2 class="page-title"><el-icon :size="22"><Checked /></el-icon> RAG 评估中心</h2>

    <el-tabs v-model="activeTab" class="eval-tabs" @tab-change="onTabChange">
      <!-- ==================== Tab 1: 检索评测 ==================== -->
      <el-tab-pane label="🔍 检索评测" name="retrieval">
        <!-- 控制卡片 -->
        <div class="surface-card">
          <div class="card-header">
            <span class="card-title">
              🎯 检索评测
              <span v-if="retPhase !== 'idle'" :class="['phase-badge', 'phase-' + retPhase]">{{ retPhaseLabel }}</span>
            </span>
            <div class="header-actions">
              <button class="gradient-btn-sm" @click="runRetrieval" :disabled="running">
                <span v-if="running && activeTab === 'retrieval'" class="btn-spinner-sm"></span>
                <el-icon v-else :size="14"><VideoPlay /></el-icon>
                {{ running && activeTab === 'retrieval' ? '评测中...' : '运行评测' }}
              </button>
              <button class="outline-btn-sm danger" @click="cancelEval" :disabled="!(running && activeTab === 'retrieval')">
                <el-icon :size="14"><Close /></el-icon> 取消
              </button>
            </div>
          </div>
          <!-- 进度条 -->
          <div v-if="(running && activeTab === 'retrieval') || retProgress.total > 0" class="progress-area">
            <div class="progress-label">
              <span>样本进度</span>
              <span class="progress-right">
                <span v-if="running && gapWarning" class="gap-warning">⏳ 后端处理中...</span>
                <span v-else class="elapsed-timer">⏱ {{ elapsed }}s</span>
                <span :style="{ color: retCancelled ? '#86909C' : '#165DFF' }">{{ retProgress.current }} / {{ retProgress.total }}</span>
              </span>
            </div>
            <el-progress :percentage="retProgress.total > 0 ? Math.round(retProgress.current / retProgress.total * 100) : 0"
              :color="retCancelled ? '#86909C' : '#165DFF'" :stroke-width="8" :striped="running && activeTab === 'retrieval'" :striped-flow="running && activeTab === 'retrieval'" />
          </div>
          <!-- 日志 -->
          <div v-if="retLogs.length" class="log-panel">
            <div class="log-header"><el-icon><Document /></el-icon> 实时日志 <button class="text-btn" @click="retLogs = []">清空</button></div>
            <div class="log-body">
              <div v-for="(log, i) in retLogs" :key="i" :class="['log-line', 'log-' + log.level]">
                <span class="log-time">{{ log.time }}</span>
                <span :class="'log-badge badge-' + log.level">{{ log.badge }}</span>
                <span>{{ log.msg }}</span>
              </div>
            </div>
          </div>
          <el-alert v-if="!running && retProgress.total === 0"
            title="检索评测对预设测试样本进行 Precision、Recall、F1、MRR、NDCG 等指标评估。需要提供标注数据（query + 期望关键词 + 相关文档ID）。"
            type="info" :closable="false" show-icon class="info-alert" />
        </div>

        <!-- 指标卡片 -->
        <div class="metric-grid" v-if="retMetrics || (running && activeTab === 'retrieval')">
          <div class="metric-card" v-for="m in retMetricCards" :key="m.label">
            <div class="metric-val" :style="{ color: m.color }">{{ m.value }}</div>
            <div class="metric-lbl">{{ m.label }}</div>
          </div>
        </div>

        <!-- 图表 -->
        <el-row :gutter="20" v-if="retHasCharts">
          <el-col :span="12">
            <div class="surface-card">
              <div class="card-header"><span class="card-title">📊 检索指标总览</span></div>
              <img v-if="retCharts.retrieval_metrics" :src="'data:image/png;base64,' + retCharts.retrieval_metrics" class="chart-img" />
              <el-empty v-else description="暂无图表" :image-size="60" />
            </div>
          </el-col>
          <el-col :span="12">
            <div class="surface-card">
              <div class="card-header"><span class="card-title">📊 关键词匹配率</span></div>
              <img v-if="retCharts.keyword_match" :src="'data:image/png;base64,' + retCharts.keyword_match" class="chart-img" />
              <el-empty v-else description="暂无图表" :image-size="60" />
            </div>
          </el-col>
        </el-row>

        <!-- 样例 -->
        <div class="surface-card" style="margin-top:var(--space-5)" v-if="retSamples.length">
          <div class="card-header"><span class="card-title">📋 评测样例（共 {{ retSamples.length }} 条）</span></div>
          <el-collapse accordion>
            <el-collapse-item v-for="(s, i) in retSamples" :key="i" :title="`Q${i+1}: ${(s.query || '').slice(0, 60)}`">
              <div class="sample-detail" v-if="!s.error">
                <p><strong>查询：</strong>{{ s.query }}</p>
                <p><strong>回答：</strong>{{ s.answer || '-' }}</p>
                <p v-if="s.expected_keywords?.length"><strong>期望关键词：</strong>{{ s.expected_keywords.join(', ') }}</p>
                <div class="sample-tags">
                  <el-tag size="small" type="primary" effect="light">P: {{ fmtPct(s.precision) }}</el-tag>
                  <el-tag size="small" type="success" effect="light">R: {{ fmtPct(s.recall) }}</el-tag>
                  <el-tag size="small" type="warning" effect="light">F1: {{ fmtPct(s.f1) }}</el-tag>
                  <el-tag size="small" effect="light">MRR: {{ fmtPct(s.mrr) }}</el-tag>
                  <el-tag size="small" type="info" effect="light">⏱ {{ s.execution_time ? s.execution_time + 's' : '-' }}</el-tag>
                </div>
              </div>
              <div v-else class="sample-detail">
                <p><strong>查询：</strong>{{ s.query }}</p>
                <el-tag type="danger">❌ {{ s.error }}</el-tag>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>

        <el-empty v-if="!retMetrics && !running && retLoaded" description="点击「运行评测」开始" :image-size="120" style="margin-top:40px;" />
      </el-tab-pane>

      <!-- ==================== Tab 2: RAGAS 评测 ==================== -->
      <el-tab-pane label="🧪 RAGAS 评测" name="ragas">
        <div class="surface-card">
          <div class="card-header">
            <span class="card-title">
              🎯 RAGAS 评测
              <span v-if="ragasPhase !== 'idle'" :class="['phase-badge', 'phase-' + ragasPhase]">{{ ragasPhaseLabel }}</span>
            </span>
            <div class="header-actions">
              <button class="gradient-btn-sm" @click="runRagas" :disabled="running">
                <span v-if="running && activeTab === 'ragas'" class="btn-spinner-sm"></span>
                <el-icon v-else :size="14"><VideoPlay /></el-icon>
                {{ running && activeTab === 'ragas' ? '评测中...' : '运行 RAGAS 评测' }}
              </button>
              <button class="outline-btn-sm danger" @click="cancelEval" :disabled="!(running && activeTab === 'ragas')">
                <el-icon :size="14"><Close /></el-icon> 取消
              </button>
            </div>
          </div>
          <!-- 进度条 -->
          <div v-if="(running && activeTab === 'ragas') || ragasProgress.total > 0" class="progress-area">
            <div class="progress-label">
              <span>样本采集进度</span>
              <span class="progress-right">
                <span v-if="running && gapWarning" class="gap-warning">⏳ 后端处理中...</span>
                <span v-else class="elapsed-timer">⏱ {{ elapsed }}s</span>
                <span :style="{ color: ragasCancelled ? '#86909C' : '#165DFF' }">{{ ragasProgress.current }} / {{ ragasProgress.total }}</span>
              </span>
            </div>
            <el-progress :percentage="ragasProgress.total > 0 ? Math.round(ragasProgress.current / ragasProgress.total * 100) : 0"
              :color="ragasCancelled ? '#86909C' : '#165DFF'" :stroke-width="8" :striped="running && !ragasEvaluating" :striped-flow="running && !ragasEvaluating" />
            <p v-if="ragasEvaluating" class="eval-phase-bar"><el-icon class="is-loading"><Loading /></el-icon> 正在计算 RAGAS 评分...</p>
          </div>
          <!-- 日志 -->
          <div v-if="ragasLogs.length" class="log-panel">
            <div class="log-header"><el-icon><Document /></el-icon> 实时日志 <button class="text-btn" @click="ragasLogs = []">清空</button></div>
            <div class="log-body">
              <div v-for="(log, i) in ragasLogs" :key="i" :class="['log-line', 'log-' + log.level]">
                <span class="log-time">{{ log.time }}</span>
                <span :class="'log-badge badge-' + log.level">{{ log.badge }}</span>
                <span>{{ log.msg }}</span>
              </div>
            </div>
          </div>
          <el-alert v-if="!running && ragasProgress.total === 0"
            title="RAGAS 评测使用 LLM 自动评估 Faithfulness、Answer Relevancy、Context Relevancy/Precision/Recall、Answer Correctness。无需标注数据，但提供 ground_truth 可评估 Answer Correctness。"
            type="info" :closable="false" show-icon class="info-alert" />
        </div>

        <div class="metric-grid" v-if="ragasResult || (running && activeTab === 'ragas')">
          <div class="metric-card" v-for="m in ragasMetricCards" :key="m.label">
            <div class="metric-val" :style="{ color: m.color }">{{ m.value }}</div>
            <div class="metric-lbl">{{ m.label }}</div>
          </div>
        </div>

        <!-- 详情 -->
        <div class="surface-card" style="margin-top:var(--space-5)" v-if="ragasDetails.length">
          <div class="card-header"><span class="card-title">📋 评测详情（共 {{ ragasDetails.length }} 条）</span></div>
          <el-table :data="ragasDetails" stripe size="small" max-height="400" class="styled-table">
            <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="answer" label="回答" min-width="180" show-overflow-tooltip />
            <el-table-column prop="context_count" label="上下文数" width="90" align="center" />
            <el-table-column prop="ground_truth" label="标准答案" min-width="120" show-overflow-tooltip />
          </el-table>
        </div>

        <el-empty v-if="!ragasResult && !running && ragasLoaded" description="点击「运行 RAGAS 评测」开始" :image-size="120" style="margin-top:40px;" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { connectEvalSSE, cancelEvaluation } from '@/api/admin'
import { useCountUp } from '@/composables/useCountUp'
import { Checked, VideoPlay, Close, Document, Loading } from '@element-plus/icons-vue'

// ── 公共状态 ──
const activeTab = ref('retrieval')
const running = ref(false)
const elapsed = ref(0)
const lastEventTime = ref(0)
const gapWarning = ref(false)
let sseConn = null
let elapsedTimer = null
let gapCheckTimer = null

function startTimers() {
  elapsed.value = 0; lastEventTime.value = Date.now(); gapWarning.value = false
  elapsedTimer = setInterval(() => { elapsed.value++ }, 1000)
  gapCheckTimer = setInterval(() => {
    if (running.value && Date.now() - lastEventTime.value > 8000) gapWarning.value = true
  }, 1000)
}
function stopTimers() { clearInterval(elapsedTimer); clearInterval(gapCheckTimer); elapsedTimer = null; gapCheckTimer = null }
function recordEvent() { lastEventTime.value = Date.now(); gapWarning.value = false }

// ── 检索评测 ──
const retLoaded = ref(false)
const retMetrics = ref(null)
const retCharts = ref(null)
const retSamples = ref([])
const retLogs = ref([])
const retProgress = ref({ current: 0, total: 0 })
const retCancelled = ref(false)
const retPhase = ref('idle')

const retPhaseLabel = computed(() => ({
  connecting: '🔗 连接中', sampling: '📊 采样中', done: '✅ 完成'
}[retPhase.value] || ''))

const countPrecision = useCountUp(computed(() => fmtVal(retMetrics.value?.precision)), 600)
const countRecall = useCountUp(computed(() => fmtVal(retMetrics.value?.recall)), 600)
const countF1 = useCountUp(computed(() => fmtVal(retMetrics.value?.f1_score)), 600)
const countMRR = useCountUp(computed(() => fmtVal(retMetrics.value?.mrr)), 600)
const countNDCG = useCountUp(computed(() => fmtVal(retMetrics.value?.ndcg)), 600)

const retMetricCards = computed(() => [
  { label: 'Precision', value: countPrecision.value.toFixed(1) + '%', color: '#165DFF' },
  { label: 'Recall', value: countRecall.value.toFixed(1) + '%', color: colorByScore(retMetrics.value?.recall) },
  { label: 'F1 Score', value: countF1.value.toFixed(1) + '%', color: colorByScore(retMetrics.value?.f1_score) },
  { label: 'MRR', value: countMRR.value.toFixed(1) + '%', color: '#FF7D00' },
  { label: 'NDCG', value: countNDCG.value.toFixed(1) + '%', color: colorByScore(retMetrics.value?.ndcg) },
])
const retHasCharts = computed(() => retCharts.value && (retCharts.value.retrieval_metrics || retCharts.value.keyword_match))

async function runRetrieval() {
  if (running.value) return
  retCancelled.value = false; running.value = true; retPhase.value = 'connecting'
  retMetrics.value = null; retCharts.value = null; retSamples.value = []; retLogs.value = []; retProgress.value = { current: 0, total: 0 }
  retLogs.value.push(makeLog('🚀 正在连接检索评测服务...', 'info')); startTimers()
  sseConn = connectEvalSSE('/admin/evaluate/stream',
    (type, data) => {
      recordEvent()
      switch (type) {
        case 'connected': retPhase.value = 'sampling'; retLogs.value.push(makeLog(`🔌 ${data.message}`, 'ok')); break
        case 'progress': retProgress.value = { current: data.current, total: data.total }; break
        case 'sample_done':
          if (data.error) retLogs.value.push(makeLog(`[${data.index + 1}] 失败: ${data.query}`, 'err'))
          else {
            retLogs.value.push(makeLog(`[${data.index + 1}] 完成`, 'ok'))
            if (data.cumulative_metrics) retMetrics.value = { ...data.cumulative_metrics.retrieval, ...data.cumulative_metrics.generation }
            if (data.sample) retSamples.value.push(data.sample)
          }
          break
        case 'complete': retPhase.value = 'done'; retMetrics.value = data.retrieval; retCharts.value = data.charts || {}; retSamples.value = data.sample_reports || []; retLogs.value.push(makeLog(`✅ 完成！${data.sample_count} 样本，${data.total_time}s`, 'ok')); finish(); break
        case 'cancelled': retLogs.value.push(makeLog('⚠ 已取消', 'warn')); retCancelled.value = true; finish(); break
        case 'error': retLogs.value.push(makeLog(`❌ ${data.message}`, 'err')); finish(); break
      }
    },
    (err) => { retLogs.value.push(makeLog(`❌ ${err}`, 'err')); finish() }
  )
}

// ── RAGAS 评测 ──
const ragasLoaded = ref(false)
const ragasResult = ref(null)
const ragasDetails = ref([])
const ragasLogs = ref([])
const ragasProgress = ref({ current: 0, total: 0 })
const ragasCancelled = ref(false)
const ragasEvaluating = ref(false)
const ragasPhase = ref('idle')

const ragasPhaseLabel = computed(() => ({
  connecting: '🔗 连接中', sampling: '📊 采样中', evaluating: '🔬 评分中', done: '✅ 完成'
}[ragasPhase.value] || ''))

const countFaith = useCountUp(computed(() => fmtVal(ragasResult.value?.faithfulness)), 600)
const countRel = useCountUp(computed(() => fmtVal(ragasResult.value?.answer_relevancy)), 600)
const countCtxRel = useCountUp(computed(() => fmtVal(ragasResult.value?.context_relevancy)), 600)
const countCtxPrec = useCountUp(computed(() => fmtVal(ragasResult.value?.context_precision)), 600)
const countCtxRec = useCountUp(computed(() => fmtVal(ragasResult.value?.context_recall)), 600)
const countCorrect = useCountUp(computed(() => fmtVal(ragasResult.value?.answer_correctness)), 600)

const ragasMetricCards = computed(() => {
  const cards = [
    { label: 'Faithfulness', value: countFaith.value.toFixed(1) + '%', color: '#165DFF' },
    { label: 'Answer Relevancy', value: countRel.value.toFixed(1) + '%', color: '#00B42A' },
    { label: 'Context Relevancy', value: countCtxRel.value.toFixed(1) + '%', color: '#FF7D00' },
    { label: 'Context Precision', value: countCtxPrec.value.toFixed(1) + '%', color: '#F53F3F' },
    { label: 'Context Recall', value: countCtxRec.value.toFixed(1) + '%', color: '#722ED1' },
  ]
  if (ragasResult.value?.answer_correctness != null)
    cards.push({ label: 'Answer Correctness', value: countCorrect.value.toFixed(1) + '%', color: colorByScore(ragasResult.value.answer_correctness) })
  return cards
})

async function runRagas() {
  if (running.value) return
  ragasCancelled.value = false; ragasEvaluating.value = false; running.value = true; ragasPhase.value = 'connecting'
  ragasResult.value = null; ragasDetails.value = []; ragasLogs.value = []; ragasProgress.value = { current: 0, total: 0 }
  ragasLogs.value.push(makeLog('🚀 正在连接 RAGAS 评测服务...', 'info')); startTimers()
  sseConn = connectEvalSSE('/admin/evaluate/ragas/stream',
    (type, data) => {
      recordEvent()
      switch (type) {
        case 'connected': ragasPhase.value = 'sampling'; ragasLogs.value.push(makeLog(`🔌 ${data.message}`, 'ok')); break
        case 'progress': ragasProgress.value = { current: data.current, total: data.total }; break
        case 'sample_done': ragasLogs.value.push(makeLog(`[${data.index + 1}] ${data.error ? '失败: ' + data.error : '完成'}`, data.error ? 'err' : 'ok')); break
        case 'evaluating': ragasPhase.value = 'evaluating'; ragasEvaluating.value = true; ragasLogs.value.push(makeLog('🔬 ' + data.message, 'warn')); break
        case 'complete': ragasPhase.value = 'done'; ragasEvaluating.value = false; ragasResult.value = data.metrics; ragasDetails.value = data.details || []; ragasLogs.value.push(makeLog(`✅ 完成！${data.sample_count} 样本，${data.total_time}s`, 'ok')); finish(); break
        case 'cancelled': ragasEvaluating.value = false; ragasLogs.value.push(makeLog('⚠ 已取消', 'warn')); ragasCancelled.value = true; finish(); break
        case 'error': ragasEvaluating.value = false; ragasLogs.value.push(makeLog(`❌ ${data.message}`, 'err')); finish(); break
      }
    },
    (err) => { ragasLogs.value.push(makeLog(`❌ ${err}`, 'err')); ragasEvaluating.value = false; finish() }
  )
}

// ── 公共 ──
function finish() { running.value = false; stopTimers(); sseConn = null }
function cancelEval() {
  const sid = sseConn?.getSessionId?.(); if (sid) cancelEvaluation(sid).catch(() => {})
  if (sseConn) { sseConn.close(); sseConn = null }
  stopTimers()
  if (activeTab.value === 'retrieval') retLogs.value.push(makeLog('⏹ 正在取消...', 'warn'))
  else ragasLogs.value.push(makeLog('⏹ 正在取消...', 'warn'))
}
function onTabChange() { if (running.value) cancelEval() }

function makeLog(msg, level) {
  const badges = { info: 'ℹ', ok: '✓', err: '✗', warn: '⚠' }
  return { msg, level, badge: badges[level] || 'ℹ', time: new Date().toTimeString().slice(0, 8) }
}
function fmtVal(v) { return v != null ? Math.round(v * 10000) / 100 : 0 }
function fmtPct(v) { return v != null ? (v * 100).toFixed(1) + '%' : '-' }
function colorByScore(v) {
  if (v == null) return '#999'
  return v >= 0.7 ? '#00B42A' : v >= 0.4 ? '#FF7D00' : '#F53F3F'
}

onMounted(() => { retLoaded.value = true; ragasLoaded.value = true })
onBeforeUnmount(() => {
  if (sseConn) { sseConn.close(); sseConn = null }
  running.value = false; stopTimers()
})
</script>

<style scoped>
.eval-page { max-width: 1200px; margin: 0 auto; }
.eval-tabs { margin-top: var(--space-4); }

/* 阶段标识 */
.phase-badge { font-size: var(--text-xs); font-weight: var(--font-semibold); padding: 2px 10px; border-radius: var(--radius-full); margin-left: var(--space-2); display: inline-block; vertical-align: middle; }
.phase-connecting { background: #FFF3E0; color: #E65100; }
.phase-sampling { background: var(--color-primary-light); color: var(--color-primary); }
.phase-evaluating { background: #F3E5F5; color: #7B1FA2; }
.phase-done { background: var(--color-success-light); color: var(--color-success); }

.info-alert { margin: var(--space-3) var(--space-5) var(--space-4); }

/* 进度条 */
.progress-area { padding: var(--space-4) var(--space-5); }
.progress-label { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); font-weight: var(--font-medium); margin-bottom: var(--space-2); color: var(--color-text-secondary); }
.progress-right { display: flex; align-items: center; gap: var(--space-2); }
.elapsed-timer { color: var(--color-text-tertiary); font-weight: var(--font-medium); font-variant-numeric: tabular-nums; }
.gap-warning { color: #E65100; font-weight: var(--font-semibold); animation: pulse-text 1.5s ease-in-out infinite; }
.eval-phase-bar { font-size: var(--text-sm); color: #FF7D00; margin-top: var(--space-2); text-align: center; display: flex; align-items: center; justify-content: center; gap: var(--space-2); }
@keyframes pulse-text { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* 日志 */
.log-panel { margin: 0 var(--space-5) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow: hidden; }
.log-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-2) var(--space-3); background: var(--color-surface-secondary); font-size: var(--text-sm); font-weight: var(--font-semibold); }
.log-body { max-height: 200px; overflow-y: auto; padding: var(--space-2) var(--space-3); background: #1e1e1e; font-family: 'Consolas', monospace; font-size: 12px; }
.log-line { padding: 2px 0; color: #d4d4d4; border-bottom: 1px solid #333; }
.log-line:last-child { border-bottom: none; }
.log-time { color: #888; margin-right: 8px; }
.log-badge { margin-right: 6px; font-weight: bold; }
.badge-info { color: #569cd6; } .badge-ok { color: #6a9955; } .badge-err { color: #f44747; } .badge-warn { color: #ce9178; }

/* 指标卡片 */
.metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: var(--space-4); margin-top: var(--space-5); }
.metric-card {
  background: var(--color-surface); border-radius: var(--radius-lg); padding: var(--space-5);
  border: 1px solid var(--color-border); box-shadow: var(--shadow-card);
  text-align: center; transition: all var(--transition-base);
}
.metric-card:hover { box-shadow: var(--shadow-floating); transform: translateY(-2px); }
.metric-val { font-size: 28px; font-weight: var(--font-extrabold); line-height: 1.2; }
.metric-lbl { font-size: var(--text-sm); color: var(--color-text-tertiary); font-weight: var(--font-medium); margin-top: 4px; }

/* 样例 */
.sample-detail { padding: var(--space-3); line-height: 1.8; font-size: var(--text-sm); }
.sample-detail p { margin-bottom: 6px; }
.sample-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: var(--space-2); }

/* 图表 */
.chart-img { width: 100%; padding: var(--space-3); }

/* 表格 */
.styled-table { --el-table-header-bg-color: var(--color-surface-secondary); }
.styled-table :deep(th.el-table__cell) {
  background: var(--color-surface-secondary) !important;
  border-bottom: 2px solid var(--color-border) !important;
  font-weight: var(--font-semibold); font-size: var(--text-sm); color: var(--color-text-secondary);
}
</style>

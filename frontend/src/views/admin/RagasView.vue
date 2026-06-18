<template>
  <!--
    RagasView.vue — 管理端 RAGAS 评测（MD3 灵动风格）
    评估控制 + 进度 + 指标卡片动画 + SSE日志 + 详情表格
  -->
  <div class="ragas-page">
    <h2 class="page-title"><el-icon :size="22"><TrendCharts /></el-icon> RAGAS 评测</h2>

    <!-- ===== 评测控制 ===== -->
    <div class="surface-card">
      <div class="card-header">
        <span class="card-title">
          🎯 评测控制
          <span v-if="phase !== 'idle'" :class="['phase-badge', 'phase-' + phase]">{{ phaseLabel }}</span>
        </span>
        <div class="header-actions">
          <button class="gradient-btn-sm" @click="runRagas" :disabled="running">
            <span v-if="running" class="btn-spinner-sm"></span>
            <el-icon v-else :size="14"><VideoPlay /></el-icon>
            {{ running ? '评测中...' : '运行 RAGAS 评测' }}
          </button>
          <button class="outline-btn-sm danger" @click="cancelRagas" :disabled="!running">
            <el-icon :size="14"><Close /></el-icon> 取消
          </button>
        </div>
      </div>

      <!-- 进度 + 耗时 + 间隔警告 -->
      <div v-if="running || progress.total > 0" class="progress-area">
        <div class="progress-label">
          <span>样本采集进度</span>
          <span class="progress-right">
            <span v-if="running && gapWarning" class="gap-warning">⏳ 后端处理中...</span>
            <span v-else class="elapsed-timer">⏱ {{ elapsed }}s</span>
            <span :style="{ color: progressColor }">{{ progress.current }} / {{ progress.total }}</span>
          </span>
        </div>
        <el-progress
          :percentage="progressPercent"
          :color="progressColor" :stroke-width="8" :striped="running && !evaluatingPhase" :striped-flow="running && !evaluatingPhase"
        />
        <p v-if="evaluatingPhase" class="eval-phase-bar">
          <el-icon class="is-loading"><Loading /></el-icon> 正在计算 RAGAS 评分...
        </p>
      </div>

      <!-- 日志 -->
      <div v-if="logs.length" class="log-panel">
        <div class="log-header">
          <el-icon><Document /></el-icon> 实时日志
          <button class="text-btn" @click="logs = []">清空</button>
        </div>
        <div class="log-body" ref="logBody">
          <div v-for="(log, i) in logs" :key="i" class="log-line">
            <span class="log-time">{{ log.time }}</span>
            <span :style="{ color: log.color }">{{ log.msg }}</span>
          </div>
        </div>
      </div>

      <el-alert
        v-if="!running && progress.total === 0"
        title="RAGAS 评测将对 Faithfulness、Answer Relevancy、Context Relevancy/Precision/Recall、Answer Correctness 进行综合评估。"
        type="info" :closable="false" show-icon class="info-alert"
      />
    </div>

    <!-- ===== 指标卡片 ===== -->
    <div class="metric-grid" v-if="ragasResult || running">
      <div class="metric-card" v-for="m in ragasMetricCards" :key="m.label">
        <div class="metric-val" :style="{ color: m.color }">{{ m.value }}</div>
        <div class="metric-lbl">{{ m.label }}</div>
      </div>
    </div>

    <!-- ===== 详情表格 ===== -->
    <div class="surface-card" style="margin-top:var(--space-5)" v-if="details.length">
      <div class="card-header"><span class="card-title">📋 评测详情（共 {{ details.length }} 条）</span></div>
      <el-table :data="details" stripe size="small" max-height="400" class="styled-table">
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="answer" label="回答" min-width="180" show-overflow-tooltip />
        <el-table-column prop="context_count" label="上下文数" width="90" align="center" />
        <el-table-column prop="ground_truth" label="标准答案" min-width="120" show-overflow-tooltip />
      </el-table>
    </div>

    <el-empty v-if="!ragasResult && !running && loaded" description="点击「运行 RAGAS 评测」开始" :image-size="120" style="margin-top:40px;" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { connectEvalSSE, cancelEvaluation } from '@/api/admin'
import { useCountUp } from '@/composables/useCountUp'
import { TrendCharts, VideoPlay, Close, Document, Loading } from '@element-plus/icons-vue'

const running = ref(false)
const evaluatingPhase = ref(false)
const loaded = ref(false)
const ragasResult = ref(null)
const details = ref([])
const logs = ref([])
const logBody = ref(null)
const progress = ref({ current: 0, total: 0 })
const cancelled = ref(false)
const phase = ref('idle') // idle | connecting | sampling | evaluating | done
const elapsed = ref(0)
const lastEventTime = ref(0)
const gapWarning = ref(false)
let sseConn = null
let elapsedTimer = null
let gapCheckTimer = null

const phaseLabel = computed(() => ({
  connecting: '🔗 连接中',
  sampling: '📊 采样中',
  evaluating: '🔬 评分中',
  done: '✅ 完成',
}[phase.value] || ''))

function startTimers() {
  elapsed.value = 0; lastEventTime.value = Date.now(); gapWarning.value = false
  elapsedTimer = setInterval(() => { elapsed.value++ }, 1000)
  gapCheckTimer = setInterval(() => {
    if (running.value && Date.now() - lastEventTime.value > 8000) gapWarning.value = true
  }, 1000)
}
function stopTimers() {
  clearInterval(elapsedTimer); clearInterval(gapCheckTimer)
  elapsedTimer = null; gapCheckTimer = null
}
function recordEvent() {
  lastEventTime.value = Date.now(); gapWarning.value = false
}

const countFaith = useCountUp(computed(() => fmtVal(ragasResult.value?.faithfulness)), 600)
const countRel = useCountUp(computed(() => fmtVal(ragasResult.value?.answer_relevancy)), 600)
const countCtxRel = useCountUp(computed(() => fmtVal(ragasResult.value?.context_relevancy)), 600)
const countCtxPrec = useCountUp(computed(() => fmtVal(ragasResult.value?.context_precision)), 600)
const countCtxRec = useCountUp(computed(() => fmtVal(ragasResult.value?.context_recall)), 600)
const countCorrect = useCountUp(computed(() => fmtVal(ragasResult.value?.answer_correctness)), 600)

const ragasMetricCards = computed(() => {
  const cards = [
    { label: 'Faithfulness（忠实度）', value: countFaith.value.toFixed(1) + '%', color: '#165DFF' },
    { label: 'Answer Relevancy', value: countRel.value.toFixed(1) + '%', color: '#00B42A' },
    { label: 'Context Relevancy', value: countCtxRel.value.toFixed(1) + '%', color: '#FF7D00' },
    { label: 'Context Precision', value: countCtxPrec.value.toFixed(1) + '%', color: '#F53F3F' },
    { label: 'Context Recall', value: countCtxRec.value.toFixed(1) + '%', color: '#722ED1' },
  ]
  if (ragasResult.value?.answer_correctness != null) {
    cards.push({
      label: 'Answer Correctness',
      value: countCorrect.value.toFixed(1) + '%',
      color: colorByScore(ragasResult.value.answer_correctness),
    })
  }
  return cards
})

const progressPercent = computed(() => progress.value.total > 0 ? Math.round(progress.value.current / progress.value.total * 100) : 0)
const progressColor = computed(() => cancelled.value ? '#86909C' : '#165DFF')

function fmtVal(v) { return v != null ? Math.round(v * 10000) / 100 : 0 }
function colorByScore(v) {
  if (v == null) return '#999'
  return v >= 0.7 ? '#00B42A' : v >= 0.4 ? '#FF7D00' : '#F53F3F'
}

function addLog(msg, color = '#d4d4d4') {
  logs.value.push({ msg, color, time: new Date().toTimeString().slice(0, 8) })
  nextTick(() => { if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight })
}

async function runRagas() {
  if (running.value) return
  cancelled.value = false; running.value = true; evaluatingPhase.value = false; phase.value = 'connecting'
  ragasResult.value = null; details.value = []; logs.value = []; progress.value = { current: 0, total: 0 }
  ElMessage.info('正在启动 RAGAS 评测...')
  addLog('🚀 正在连接 RAGAS 评测服务...', '#569cd6')
  startTimers()

  try {
    sseConn = connectEvalSSE('/admin/evaluate/ragas/stream',
      (eventType, data) => {
        recordEvent()
        switch (eventType) {
          case 'connected': phase.value = 'sampling'; addLog(`🔌 ${data.message}`, '#6a9955'); break
          case 'progress': progress.value = { current: data.current, total: data.total }; addLog(`[${data.current}/${data.total}] ${data.question}`, '#569cd6'); break
          case 'sample_done': addLog(`[${data.index + 1}] ${data.error ? '失败: ' + data.error : '完成'}`, data.error ? '#f44747' : '#6a9955'); break
          case 'evaluating': phase.value = 'evaluating'; evaluatingPhase.value = true; addLog('🔬 ' + data.message, '#ce9178'); break
          case 'complete': phase.value = 'done'; evaluatingPhase.value = false; ragasResult.value = data.metrics; details.value = data.details || []; addLog(`✅ 完成！${data.sample_count} 样本，${data.total_time}s`, '#6a9955'); running.value = false; stopTimers(); sseConn = null; break
          case 'cancelled': evaluatingPhase.value = false; addLog('⚠ 已取消', '#ce9178'); cancelled.value = true; running.value = false; stopTimers(); sseConn = null; break
          case 'error': evaluatingPhase.value = false; addLog(`❌ ${data.message}`, '#f44747'); running.value = false; stopTimers(); sseConn = null; break
        }
      },
      (err) => { addLog(`❌ ${err}`, '#f44747'); evaluatingPhase.value = false; running.value = false; stopTimers(); sseConn = null }
    )
  } catch (e) {
    addLog(`❌ 评测启动失败: ${e.message}`, '#f44747')
    running.value = false; stopTimers(); sseConn = null
  }
}

function cancelRagas() {
  const sid = sseConn?.getSessionId?.(); if (sid) cancelEvaluation(sid).catch(() => {})
  if (sseConn) { sseConn.close(); sseConn = null }
  stopTimers()
  addLog('⏹ 正在取消...', '#ce9178')
}

onMounted(() => { loaded.value = true })
onBeforeUnmount(() => {
  if (sseConn) {
    sseConn.close()
    sseConn = null
  }
  // 确保在组件卸载时清理所有状态（防止遗留影响其它页面）
  running.value = false
  evaluatingPhase.value = false
  phase.value = 'idle'
  stopTimers()
})
</script>

<style scoped>
.ragas-page { max-width: 1200px; margin: 0 auto; }

/* 阶段标识 */
.phase-badge { font-size: var(--text-xs); font-weight: var(--font-semibold); padding: 2px 10px; border-radius: var(--radius-full); margin-left: var(--space-2); display: inline-block; vertical-align: middle; letter-spacing: 0.02em; }
.phase-connecting { background: #FFF3E0; color: #E65100; }
.phase-sampling { background: var(--color-primary-light); color: var(--color-primary); }
.phase-evaluating { background: #F3E5F5; color: #7B1FA2; }
.phase-done { background: var(--color-success-light); color: var(--color-success); }

/* 进度 */
.progress-area { padding: var(--space-4) var(--space-5); }
.progress-label { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); font-weight: var(--font-medium); margin-bottom: var(--space-2); color: var(--color-text-secondary); }
.progress-right { display: flex; align-items: center; gap: var(--space-2); }
.elapsed-timer { color: var(--color-text-tertiary); font-weight: var(--font-medium); font-variant-numeric: tabular-nums; }
.gap-warning { color: #E65100; font-weight: var(--font-semibold); animation: pulse-text 1.5s ease-in-out infinite; }
@keyframes pulse-text { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.eval-phase-bar { font-size: var(--text-sm); color: #FF7D00; margin-top: var(--space-2); text-align: center; display: flex; align-items: center; justify-content: center; gap: var(--space-2); }
.info-alert { margin: var(--space-3) var(--space-5) var(--space-4); }

/* 日志 */
.log-panel { margin: 0 var(--space-5) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow: hidden; }
.log-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-2) var(--space-3); background: var(--color-surface-secondary); font-size: var(--text-sm); font-weight: var(--font-semibold); }
.log-body { max-height: 200px; overflow-y: auto; padding: var(--space-2) var(--space-3); background: #1e1e1e; font-family: 'Consolas', monospace; font-size: 12px; }
.log-line { padding: 2px 0; border-bottom: 1px solid #333; }
.log-line:last-child { border-bottom: none; }
.log-time { color: #888; margin-right: 8px; }

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

/* 表格 */
.styled-table { --el-table-header-bg-color: var(--color-surface-secondary); }
.styled-table :deep(th.el-table__cell) {
  background: var(--color-surface-secondary) !important;
  border-bottom: 2px solid var(--color-border) !important;
  font-weight: var(--font-semibold); font-size: var(--text-sm); color: var(--color-text-secondary);
}
.styled-table :deep(.el-table__row--striped td) { background: var(--color-surface-secondary) !important; }
.styled-table :deep(tr:hover > td) { background: rgba(22,93,255,0.04) !important; }
</style>
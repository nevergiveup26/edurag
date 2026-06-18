<template>
  <div class="wb-page">

    <!-- ====== 页面标题 ====== -->
    <div class="page-title">
      <el-icon :size="20"><Notebook /></el-icon>
      <span>错题集 · 艾宾浩斯复习</span>
      <el-tag v-if="ebbinghausData.needs_review_count > 0" type="danger" size="small" style="margin-left:auto;" effect="dark">
        {{ ebbinghausData.needs_review_count }} 题需要复习
      </el-tag>
    </div>

    <!-- ====== 艾宾浩斯遗忘曲线 ====== -->
    <div class="surface-card chart-card" style="margin-bottom:var(--space-5);">
      <div class="card-header">
        <span class="card-title">📈 艾宾浩斯遗忘曲线</span>
        <button class="outline-btn-sm" @click="loadEbbinghaus">更新曲线</button>
      </div>
      <div style="padding:var(--space-4);">
        <div v-loading="chartLoading" class="chart-container">
          <v-chart ref="chartRef" :option="chartOption" style="height: 280px; width: 100%;" />
        </div>
        <div v-if="ebbinghausData.review_schedule?.length" class="schedule-list">
          <el-tag
            v-for="schedule in ebbinghausData.review_schedule" :key="schedule.days"
            size="small" type="info" class="schedule-tag"
          >
            {{ schedule.label }}: {{ schedule.description }}
          </el-tag>
        </div>
      </div>
    </div>

    <!-- ====== 统计卡片 ====== -->
    <div class="stat-grid" style="margin-bottom:var(--space-5);">
      <div class="stat-card">
        <div class="stat-label">总错题数</div>
        <div class="stat-value">{{ stats.total || 0 }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">待复习</div>
        <div class="stat-value" style="color:var(--color-danger);">{{ needsReviewCount }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">涉及学科</div>
        <div class="stat-value" style="color:var(--color-accent);">{{ subjectList.length }}</div>
      </div>
    </div>

    <!-- ====== 过滤栏 ====== -->
    <div class="surface-card" style="margin-bottom:var(--space-5);">
      <div style="padding:var(--space-4); display:flex; align-items:center; gap:var(--space-3); flex-wrap:wrap;">
        <el-radio-group v-model="filterSubject" @change="loadList">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button v-for="s in subjectList" :key="s" :label="s">{{ s }}</el-radio-button>
        </el-radio-group>
        <button class="outline-btn-sm" @click="refreshAll" :disabled="loading">
          <el-icon :size="14"><Refresh /></el-icon> 刷新
        </button>
      </div>
    </div>

    <!-- ====== 错题列表 ====== -->
    <div class="surface-card">
      <div class="card-header">
        <span class="card-title">📋 错题记录（共 {{ list.length }} 条）</span>
      </div>
      <div style="padding:0;">
        <div v-if="loading" class="wb-loading">
          <el-icon :size="28" class="is-loading"><Loading /></el-icon>
        </div>
        <el-empty v-else-if="!list.length" description="暂无错题，继续保持！" :image-size="120" />

        <el-collapse v-else v-model="activeItems" class="wb-collapse">
          <el-collapse-item
            v-for="(item, i) in list"
            :key="item.id"
            :name="item.id"
            class="wb-item"
          >
            <template #title>
              <div class="wb-header">
                <el-tag size="small" :type="item.question_type==='objective'?'primary':'success'">
                  {{ item.question_type === 'objective' ? '客观题' : '主观题' }}
                </el-tag>
                <el-tag size="small" type="info">{{ item.subject }}</el-tag>
                <el-tag
                  :type="getItemNeedsReview(item.id) ? 'danger' : 'success'"
                  size="small"
                >
                  {{ getItemNeedsReview(item.id) ? '需要复习' : '已复习' }}
                </el-tag>
                <span class="wb-meta">{{ (item.created_at || '').slice(0, 10) }}</span>
                <span class="wb-meta">复习{{ item.review_count || 0 }}次</span>
                <span class="wb-question-preview">{{ (item.question || '').slice(0, 40) }}{{ (item.question || '').length > 40 ? '...' : '' }}</span>
                <el-popconfirm title="确定删除？" @confirm="del(item.id)">
                  <template #reference>
                    <button class="text-btn" @click.stop>删除</button>
                  </template>
                </el-popconfirm>
              </div>
            </template>

            <div class="wb-body">
              <!-- 题目 -->
              <div class="wb-question" v-if="item.question">
                <b>题目：</b>{{ item.question }}
              </div>

              <!-- 作答对比 -->
              <el-row :gutter="16" class="wb-answers">
                <el-col :span="12">
                  <div class="ans-box ans-user">
                    <div class="ans-label">📝 我的作答</div>
                    <div>{{ item.user_answer || '(空)' }}</div>
                  </div>
                </el-col>
                <el-col :span="12" v-if="item.correct_answer">
                  <div class="ans-box ans-correct">
                    <div class="ans-label">✅ 正确答案</div>
                    <div>{{ item.correct_answer }}</div>
                  </div>
                </el-col>
              </el-row>

              <!-- 批改详情 -->
              <div v-if="item.grading" class="wb-grading">
                <div class="grade-score">
                  <span :style="{fontSize:'24px',fontWeight:'700',color:item.grading.score >= 60 ? 'var(--color-success)' : 'var(--color-danger)'}">
                    {{ item.grading.score }}/{{ item.grading.max_score }}
                  </span>
                </div>
                <div class="grade-fb" v-if="item.grading.feedback">{{ item.grading.feedback }}</div>

                <div v-if="item.grading.steps?.length" class="grade-steps">
                  <div v-for="(s, si) in item.grading.steps" :key="si" class="gstep">
                    <el-tag size="small" :type="s.status==='correct'?'success':s.status==='wrong'?'danger':'warning'">
                      {{ s.step || s.description }}
                    </el-tag>
                    <span class="gstep-score">{{ s.score || s.student_score }}/{{ s.max || s.max_score }}</span>
                  </div>
                </div>

                <div v-if="item.grading.highlights?.length" class="grade-highlights">
                  <span v-for="(h, hi) in item.grading.highlights.slice(0, 5)" :key="hi" class="highlight-tag">
                    {{ (h.error_type || h.reason || '错误').slice(0, 20) }}
                  </span>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="wb-actions">
                <button class="outline-btn-sm" :disabled="analogyLoading[item.id]" @click="showAnalogyDialog(item.id)">
                  <el-icon :size="14"><TrendCharts /></el-icon> 举一反三
                </button>
                <button
                  class="outline-btn-sm"
                  :class="{ 'is-review': getItemNeedsReview(item.id) }"
                  :disabled="!getItemNeedsReview(item.id)"
                  @click="markReviewed(item.id)"
                >
                  <el-icon :size="14"><CircleCheck /></el-icon> 标记已复习
                </button>
                <div v-if="getItemEbbinghausInfo(item.id)" class="ebbing-info">
                  遗忘率: {{ 100 - getItemEbbinghausInfo(item.id).estimated_retention }}%
                  · 下次复习: {{ getItemEbbinghausInfo(item.id).next_review_in_days }} 天后
                </div>
              </div>

              <!-- 举一反三变式题 -->
              <el-collapse-transition>
                <div v-if="analogyExpanded[item.id]" class="analogy-section">
                  <el-divider content-position="left">举一反三 · 变式练习</el-divider>
                  <p class="knowledge-point" v-if="currentAnalogyResult.knowledge_point">
                    <b>知识点：</b>{{ currentAnalogyResult.knowledge_point }}
                  </p>
                  <div v-for="(variant, idx) in currentAnalogyResult.variants" :key="idx" class="variant-item">
                    <div class="surface-card variant-card">
                      <div class="card-header">
                        <span class="card-title">第 {{ idx + 1 }} 题</span>
                      </div>
                      <div style="padding:var(--space-4);">
                        <div class="variant-question"><b>题目：</b>{{ variant.question }}</div>
                        <div class="variant-hint" v-if="variant.hint">
                          <el-collapse>
                            <el-collapse-item title="💡 提示" name="hint">
                              {{ variant.hint }}
                            </el-collapse-item>
                          </el-collapse>
                        </div>
                        <div class="variant-answer">
                          <el-collapse>
                            <el-collapse-item title="📖 参考答案" name="answer">
                              {{ variant.reference_answer }}
                            </el-collapse-item>
                          </el-collapse>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </el-collapse-transition>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>

  </div> <!-- wb-page -->
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  getWrongBook, getWrongBookStats, deleteWrongBook,
  getAnalogyQuestions, getEbbinghausCurve, reviewWrongQuestion,
} from '@/api/index'
import { ElMessage } from 'element-plus'
import { Notebook, Refresh, Loading, TrendCharts, CircleCheck } from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import 'echarts'

const loading = ref(false)
const chartLoading = ref(false)
const stats = ref({})
const list = ref([])
const filterSubject = ref('')
const activeItems = ref([])

// --- 艾宾浩斯遗忘曲线 ---
const ebbinghausData = ref({ curve: [], items: [], review_schedule: [], total_items: 0, needs_review_count: 0 })

const chartOption = computed(() => {
  const curve = ebbinghausData.value.curve || []
  const items = ebbinghausData.value.items || []
  return {
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        const pts = Array.isArray(params) ? params : [params]
        return pts.map(p => `${p.marker} ${p.seriesName}: ${p.value[1]}%<br/>(${p.value[0]})`).join('<br/>')
      },
    },
    legend: { data: ['理论遗忘曲线', '当前错题'], top: 0, textStyle: { fontSize: 12 } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: 40, containLabel: true },
    xAxis: {
      type: 'value', name: '时间', nameLocation: 'middle', nameGap: 30,
      axisLabel: { formatter(val) { if (val < 1) return Math.round(val*60)+'min'; if (val < 24) return val+'h'; return (val/24).toFixed(1)+'天' } },
    },
    yAxis: { type: 'value', name: '记忆保留率 (%)', max: 100, min: 0, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: '理论遗忘曲线', type: 'line', smooth: true,
        data: curve.map(p => [p.hours, p.retention]),
        lineStyle: { color: '#E6A23C', width: 3 }, itemStyle: { color: '#E6A23C' },
        symbol: 'circle', symbolSize: 10,
        markLine: { silent: true, lineStyle: { type: 'dashed', color: '#909399' }, data: [{ yAxis: 50, label: { formatter: '50% 临界线' } }] },
      },
      {
        name: '当前错题', type: 'scatter',
        data: items.map(it => [it.hours_since, it.estimated_retention || 30]),
        symbolSize(val) { const idx = val[0]?.dataIndex; if (idx==null) return 8; return items[idx]?.needs_review ? 14 : 8 },
        itemStyle: { color(param) { const idx = param.dataIndex; if (idx==null) return '#409EFF'; return items[idx]?.needs_review ? '#F56C6C' : '#67C23A' } },
        label: { show: true, formatter(param) { const idx = param.dataIndex; if (idx==null) return ''; return (items[idx]?.question || '').slice(0, 6)+'...' }, position: 'top', fontSize: 10, color: '#666' },
      },
    ],
  }
})

const needsReviewCount = computed(() => ebbinghausData.value.needs_review_count || 0)
function getItemEbbinghausInfo(wbId) { return (ebbinghausData.value.items || []).find(i => i.id === wbId) || null }
function getItemNeedsReview(wbId) { const info = getItemEbbinghausInfo(wbId); return info ? info.needs_review : false }

// --- 举一反三 ---
const analogyLoading = ref({})
const analogyExpanded = ref({})
const analogyResults = ref({})
const currentAnalogyResult = ref({ variants: [], knowledge_point: '' })

async function showAnalogyDialog(wbId) {
  if (analogyExpanded.value[wbId]) { analogyExpanded.value[wbId] = false; return }
  if (analogyResults.value[wbId]) { currentAnalogyResult.value = analogyResults.value[wbId]; analogyExpanded.value[wbId] = true; return }
  analogyLoading.value[wbId] = true
  try {
    const res = await getAnalogyQuestions(wbId)
    analogyResults.value[wbId] = res
    currentAnalogyResult.value = res
    analogyExpanded.value[wbId] = true
    ElMessage.success('已生成变式题')
  } catch (e) { ElMessage.error('生成失败，请稍后重试') }
  finally { analogyLoading.value[wbId] = false }
}

async function markReviewed(wbId) {
  try {
    await reviewWrongQuestion(wbId)
    ElMessage.success('已标记复习')
    const item = list.value.find(i => i.id === wbId)
    if (item) item.review_count = (item.review_count || 0) + 1
    loadEbbinghaus()
  } catch (e) { ElMessage.error('操作失败') }
}

async function loadEbbinghaus() { chartLoading.value = true; try { ebbinghausData.value = await getEbbinghausCurve() } catch (e) { /* */ } finally { chartLoading.value = false } }
async function loadStats() { try { stats.value = await getWrongBookStats() } catch (e) { /* */ } }
async function loadList() { loading.value = true; try { const res = await getWrongBook(filterSubject.value || undefined); list.value = res.wrong_book || [] } catch (e) { /* */ } finally { loading.value = false } }
async function refreshAll() { await Promise.all([loadList(), loadStats(), loadEbbinghaus()]) }
async function del(id) { try { await deleteWrongBook(id); ElMessage.success('已删除'); refreshAll() } catch (e) { ElMessage.error('删除失败') } }

const subjectList = computed(() => {
  const subs = new Set()
  list.value.forEach(i => { if (i.subject) subs.add(i.subject) })
  return [...subs]
})

onMounted(() => { loadStats(); loadList(); loadEbbinghaus() })
</script>

<style scoped>
.wb-page { max-width: 960px; margin: 0 auto; }

/* ===== 图表卡片 ===== */
.chart-card .card-header { justify-content: space-between; }
.chart-container { min-height: 280px; }
.schedule-list { margin-top: var(--space-4); display: flex; flex-wrap: wrap; gap: var(--space-2); }
.schedule-tag { font-size: var(--text-xs); }

/* ===== 加载状态 ===== */
.wb-loading { text-align: center; padding: var(--space-10); color: var(--color-text-tertiary); }

/* ===== 折叠面板 ===== */
.wb-collapse {
  border: none;
}
.wb-collapse :deep(.el-collapse-item__header) {
  height: auto;
  padding: 0;
  border-bottom: 1px solid var(--color-divider);
  font-size: inherit;
  line-height: inherit;
}
.wb-collapse :deep(.el-collapse-item__header.is-active) {
  border-bottom-color: var(--color-primary);
}
.wb-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 1px solid var(--color-divider);
}
.wb-collapse :deep(.el-collapse-item__content) {
  padding: 0;
}

/* ===== 错题列表项 ===== */
.wb-item {
  transition: background var(--transition-fast);
}
.wb-item:hover { background: var(--color-surface-secondary); }

.wb-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  width: 100%;
  cursor: pointer;
  min-height: 44px;
}
.wb-question-preview {
  flex: 1;
  min-width: 120px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wb-body {
  padding: var(--space-4) var(--space-5);
}
.wb-meta {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--font-medium);
}

.wb-question {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-3);
  color: var(--color-text-primary);
}

.wb-answers { margin-top: var(--space-2); }
.ans-box {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}
.ans-user {
  background: var(--color-accent-light);
  border: 1px solid rgba(212, 155, 58, 0.15);
}
.ans-correct {
  background: var(--color-success-light);
  border: 1px solid rgba(45, 157, 127, 0.15);
}
.ans-label {
  font-weight: var(--font-semibold);
  margin-bottom: var(--space-2);
  font-size: var(--text-xs);
  letter-spacing: 0.02em;
}

/* ===== 批改详情 ===== */
.wb-grading {
  margin-top: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}
.grade-score { text-align: center; margin-bottom: var(--space-2); }
.grade-fb {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-3);
}
.grade-steps { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.gstep { display: flex; align-items: center; gap: var(--space-2); }
.gstep-score { font-size: var(--text-xs); color: var(--color-text-tertiary); font-weight: var(--font-medium); }
.grade-highlights { margin-top: var(--space-3); display: flex; flex-wrap: wrap; gap: var(--space-1); }
.highlight-tag {
  display: inline-block;
  padding: 2px 8px;
  background: var(--color-danger-light);
  border-radius: var(--radius-xs);
  font-size: var(--text-xs);
  color: var(--color-danger);
  font-weight: var(--font-medium);
}

/* ===== 操作按钮区域 ===== */
.wb-actions {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-divider);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.ebbing-info {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--font-medium);
  margin-left: var(--space-2);
}

/* ===== 举一反三 ===== */
.analogy-section {
  margin-top: var(--space-4);
  padding: var(--space-4);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}
.knowledge-point {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-3);
  line-height: var(--leading-relaxed);
}
.variant-item { margin-bottom: var(--space-3); }
.variant-item:last-child { margin-bottom: 0; }
.variant-card { margin-bottom: 0 !important; }
.variant-card .card-header {
  justify-content: flex-start;
  color: var(--color-primary);
  font-weight: var(--font-bold);
}
.variant-question {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text-primary);
  margin-bottom: var(--space-3);
}
.variant-hint, .variant-answer { margin-top: var(--space-2); }

/* ===== 暗黑模式 ===== */
html.dark .wb-item:hover { background: var(--color-surface-secondary); }
html.dark .wb-grading { background: var(--color-surface-secondary); border-color: var(--color-border); }
html.dark .analogy-section { background: var(--color-surface-secondary); border-color: var(--color-border); }
html.dark .highlight-tag { background: rgba(209, 80, 80, 0.12); }
</style>
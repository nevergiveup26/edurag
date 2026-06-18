<template>
  <!--
    DashboardView.vue — 管理端仪表盘（MD3 灵动风格）
    统计卡片 + ECharts 图表 + 最近文档表格
  -->
  <div class="dashboard-page">
    <h2 class="page-title"><el-icon :size="22"><DataBoard /></el-icon> 仪表盘</h2>

    <!-- ===== 统计卡片 ===== -->
    <div class="stat-grid" v-loading="loading">
      <div class="stat-card" v-for="card in statCards" :key="card.label">
        <div class="stat-icon" :style="{ background: card.bg, color: card.color }">
          <el-icon :size="20"><component :is="card.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-value" :style="{ color: card.color }">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
        </div>
      </div>
    </div>

    <!-- ===== 图表区 ===== -->
    <el-row :gutter="20">
      <el-col :span="12">
        <div class="surface-card">
          <div class="card-header">
            <span class="card-title">📊 查询趋势（近7天）</span>
          </div>
          <div ref="chart1Ref" class="chart-box"></div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="surface-card">
          <div class="card-header">
            <span class="card-title">📁 文档类型分布</span>
          </div>
          <div ref="chart2Ref" class="chart-box"></div>
        </div>
      </el-col>
    </el-row>

    <!-- ===== 最近文档表格 ===== -->
    <div class="surface-card" style="margin-top: var(--space-5)">
      <div class="card-header">
        <span class="card-title">📄 最近上传文档</span>
        <el-tag size="small" effect="plain">{{ recentDocs.length }} 条</el-tag>
      </div>
      <el-table :data="recentDocs" stripe size="small" empty-text="暂无文档" class="styled-table">
        <el-table-column prop="id" label="ID" width="90" align="center">
          <template #default="{ row }"><code class="id-code">{{ row.id?.slice(0, 8) }}</code></template>
        </el-table-column>
        <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="title-cell">
              <el-icon :size="14" class="title-icon"><Document /></el-icon>
              {{ row.filename }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="getTypeColor(row.file_type)" effect="light" round>{{ row.file_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="块数" width="80" align="center" />
        <el-table-column prop="upload_time" label="上传时间" width="170" align="center">
          <template #default="{ row }">{{ formatTime(row.upload_time) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { getAdminStats } from '@/api/admin'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { DataBoard, Document } from '@element-plus/icons-vue'

const router = useRouter()
const loading = ref(false)
const stats = ref({})
const recentDocs = ref([])
const chart1Ref = ref(null)
const chart2Ref = ref(null)
const chartInstances = []
const resizeHandlers = []

function safeInit(domRef) {
  if (!domRef.value) return null
  const existing = echarts.getInstanceByDom(domRef.value)
  if (existing) existing.dispose()
  return echarts.init(domRef.value)
}

const statCards = computed(() => [
  { label: '文档总数', value: stats.value.total_documents || 0, icon: 'Document', bg: '#E8F0FF', color: '#165DFF' },
  { label: '知识块数', value: stats.value.total_chunks || 0, icon: 'Grid', bg: '#E8FFEA', color: '#00B42A' },
  { label: '用户数', value: stats.value.total_users || 0, icon: 'UserFilled', bg: '#FFF7E8', color: '#FF7D00' },
  { label: '总查询量', value: stats.value.total_queries || 0, icon: 'ChatLineSquare', bg: '#FFECE8', color: '#F53F3F' },
])

function formatTime(t) { return t ? new Date(t).toLocaleString('zh-CN') : '-' }
function getTypeColor(type) {
  const m = { pdf: 'danger', docx: 'primary', txt: 'success', md: 'warning', html: 'info' }
  return m[type] || 'info'
}

async function loadData() {
  loading.value = true
  try {
    const res = await getAdminStats()
    stats.value = res
    recentDocs.value = (res.recent_documents || []).slice(0, 10)
    nextTick(() => initCharts())
  } catch (_) {} finally { loading.value = false }
}

function initCharts() {
  // 清理旧实例
  chartInstances.forEach(c => c.dispose())
  chartInstances.length = 0
  resizeHandlers.forEach(h => window.removeEventListener('resize', h))
  resizeHandlers.length = 0

  const c1 = safeInit(chart1Ref)
  if (c1) {
    const trend = stats.value.query_trend || []
    const xData = trend.length ? trend.map(t => t.date) : ['--']
    const yData = trend.length ? trend.map(t => t.count) : [0]
    c1.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: xData, axisLine: { lineStyle: { color: '#E5E6EB' } } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#F2F3F5' } } },
      series: [{
        data: yData,
        type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(22,93,255,0.15)' }, { offset: 1, color: 'rgba(22,93,255,0)' }] } },
        lineStyle: { color: '#165DFF', width: 2 },
        itemStyle: { color: '#165DFF' },
      }],
    })
    const h1 = () => c1.resize()
    window.addEventListener('resize', h1)
    chartInstances.push(c1)
    resizeHandlers.push(h1)
  }

  const c2 = safeInit(chart2Ref)
  if (c2) {
    const types = stats.value.doc_type_dist || []
    c2.setOption({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: '#86909C', fontSize: 12 } },
      series: [{
        type: 'pie', radius: ['45%', '72%'], center: ['50%', '45%'],
        data: types.length ? types : [{ value: 10, name: 'PDF' }, { value: 5, name: 'DOCX' }, { value: 3, name: 'TXT' }],
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.15)' } },
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
      }],
    })
    const h2 = () => c2.resize()
    window.addEventListener('resize', h2)
    chartInstances.push(c2)
    resizeHandlers.push(h2)
  }
}

onMounted(loadData)
onUnmounted(() => {
  chartInstances.forEach(c => c.dispose())
  chartInstances.length = 0
  resizeHandlers.forEach(h => window.removeEventListener('resize', h))
  resizeHandlers.length = 0
})
</script>

<style scoped>
.dashboard-page { max-width: 1200px; margin: 0 auto; }

/* ===== 统计卡片 ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}
.stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-card);
  transition: all var(--transition-base);
}
.stat-card:hover {
  box-shadow: var(--shadow-floating);
  transform: translateY(-2px);
  border-color: var(--color-primary);
}
.stat-icon {
  width: 48px; height: 48px;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-lg);
  flex-shrink: 0;
}
.stat-body { flex: 1; min-width: 0; }
.stat-value {
  font-size: 30px;
  font-weight: var(--font-extrabold);
  line-height: var(--leading-tight);
}
.stat-label {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  font-weight: var(--font-medium);
  margin-top: 2px;
}

/* ===== 图表区 ===== */
.chart-box { height: 300px; padding: var(--space-3) var(--space-4); }

.title-cell { display: flex; align-items: center; gap: var(--space-2); }
.title-icon { color: var(--color-text-tertiary); flex-shrink: 0; }

/* 暗黑 */
html.dark .styled-table :deep(th.el-table__cell) { background: var(--color-surface-secondary) !important; }
</style>
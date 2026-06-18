<template>
  <div class="kg-page">
    <!-- 顶部统计 -->
    <div class="kg-header">
      <h2 class="kg-title">
        <el-icon :size="22"><Share /></el-icon>
        知识图谱探索
      </h2>
      <p class="kg-subtitle">可视化浏览知识点之间的关联关系</p>
    </div>

    <div v-if="stats" class="kg-stats">
      <div class="stat-card" v-for="s in statCards" :key="s.label">
        <div class="stat-val" :style="{ color: s.color }">{{ s.value }}</div>
        <div class="stat-lbl">{{ s.label }}</div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="kg-filter">
      <el-select v-model="filterGrade" placeholder="选择学段" clearable size="small" @change="onFilterChange">
        <el-option label="小学" value="小学" />
        <el-option label="初中" value="初中" />
        <el-option label="高中" value="高中" />
      </el-select>
      <el-select v-model="filterSubject" placeholder="选择学科" clearable size="small">
        <el-option v-for="sub in subjectList" :key="sub" :label="sub" :value="sub" />
      </el-select>
      <el-button
        type="primary"
        size="small"
        :loading="loading"
        :disabled="!filterGrade || !filterSubject"
        @click="handleLoadClick"
      >
        加载图谱
      </el-button>
      <span v-if="stats" class="filter-hint">
        共 {{ stats.entity_count || 0 }} 个知识点 / {{ stats.relation_count || 0 }} 条关系
      </span>
      <span v-else-if="!filterGrade || !filterSubject" class="filter-hint filter-hint-warn">
        请选择学段 + 学科后点击加载
      </span>
    </div>

    <!-- 图表区域 -->
    <div class="kg-main">
      <div v-loading="loading" class="kg-chart-wrap">
        <!-- 未加载时显示空状态 -->
        <div v-if="!rawData && !loading" class="kg-empty">
          <el-icon :size="48" color="#c9cdd4"><Share /></el-icon>
          <p class="empty-title">选择学段和学科后点击"加载图谱"</p>
          <p class="empty-desc">建议每次只加载一个学科（约 500-800 个知识点），体验最流畅</p>
        </div>
        <div ref="chartRef" class="kg-chart" :style="{ display: rawData ? 'block' : 'none' }"></div>
      </div>

      <!-- 实体详情面板 -->
      <div v-if="selectedEntity" class="kg-detail">
        <div class="detail-header">
          <h3 class="detail-title">{{ selectedEntity.display_name || selectedEntity.name }}</h3>
          <button class="detail-close" @click="selectedEntity = null">
            <el-icon :size="14"><Close /></el-icon>
          </button>
        </div>
        <div class="detail-body">
          <!-- 完整路径（仅 CK12 实体显示） -->
          <div v-if="selectedEntity.display_name && selectedEntity.display_name !== selectedEntity.name" class="detail-path">
            <span class="path-label">完整路径：</span>{{ selectedEntity.name }}
          </div>
          <div class="detail-tag-wrap">
            <el-tag size="small" :type="typeColorMap[selectedEntity.type] || 'info'" effect="light" round>
              {{ selectedEntity.type || '未知' }}
            </el-tag>
            <el-tag v-if="selectedEntity.subject" size="small" type="primary" effect="plain" round>
              {{ selectedEntity.subject }}
            </el-tag>
            <el-tag v-if="selectedEntity.grade" size="small" type="warning" effect="plain" round>
              {{ selectedEntity.grade }}
            </el-tag>
          </div>
          <p v-if="selectedEntity.description" class="detail-desc">
            {{ selectedEntity.description }}
          </p>
          <div v-if="neighbors.length" class="detail-section">
            <h4 class="detail-section-title">关联实体 ({{ neighbors.length }})</h4>
            <div class="neighbor-list">
              <div
                v-for="n in neighbors"
                :key="n.name"
                class="neighbor-item"
                @click="focusEntity(n.name)"
              >
                <span class="neighbor-name">{{ n.display_name || n.name }}</span>
                <el-tag size="small" type="info" effect="plain">{{ n.relation }}</el-tag>
              </div>
            </div>
          </div>
          <div v-else class="detail-empty">暂无关联实体</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Share, Close } from '@element-plus/icons-vue'
import { getKnowledgeGraphData, getKnowledgeGraphStats, getEntityDetail } from '@/api/index'
import * as echarts from 'echarts'

const chartRef = ref(null)
const chart = ref(null)
const loading = ref(false)
const rawData = ref(null)
const stats = ref(null)
const selectedEntity = ref(null)
const neighbors = ref([])

// 筛选状态
const filterSubject = ref('')
const filterGrade = ref('')

// 所有学科列表（从图谱 stats 动态加载，避免与数据不匹配）
const subjectList = ref([])

async function fetchStats(grade) {
  try {
    const res = await getKnowledgeGraphStats(grade)
    stats.value = res
    const dist = res.subject_distribution || {}
    subjectList.value = Object.keys(dist).filter(s => s).sort()
  } catch (e) {
    console.error('获取图谱统计失败', e)
  }
}

const typeColorMap = {
  '概念': 'primary',
  '公式': 'success',
  '人物': 'warning',
  '事件': 'danger',
  '学科域': 'primary',
  '一级知识点': 'success',
  '二级知识点': 'warning',
  '三级知识点': 'danger',
  '四级知识点': 'info',
  '细分知识点': 'info',
  '未知': 'info',
}

const entityColors = {
  '概念': '#4B5EE4',
  '公式': '#00B42A',
  '人物': '#FF7D00',
  '事件': '#F53F3F',
  '学科域': '#4B5EE4',
  '一级知识点': '#00B42A',
  '二级知识点': '#FF7D00',
  '三级知识点': '#F53F3F',
  '四级知识点': '#722ED1',
  '细分知识点': '#0FC6C2',
  '未知': '#86909C',
}

const statCards = computed(() => {
  if (!stats.value) return []
  return [
    { label: '实体总数', value: stats.value.entity_count || 0, color: '#4B5EE4' },
    { label: '关系总数', value: stats.value.relation_count || 0, color: '#00B42A' },
  ]
})

function buildChartOption(data) {
  const entities = data.entities || []
  const relations = data.relations || []

  // 统计每个实体的关联数
  const degreeMap = {}
  relations.forEach(r => {
    degreeMap[r.source] = (degreeMap[r.source] || 0) + 1
    degreeMap[r.target] = (degreeMap[r.target] || 0) + 1
  })

  const totalNodes = entities.length
  // 大图谱优化：超过 500 节点时减少标签显示
  const labelThreshold = totalNodes > 500 ? 5 : totalNodes > 200 ? 3 : 2

  const nodes = entities.map(e => {
    const degree = degreeMap[e.name] || 1
    const displayName = e.display_name || e.name
    return {
      id: e.name,
      name: displayName,  // ECharts 显示名
      value: degree,
      symbolSize: Math.min(30, Math.max(10, 8 + degree * 2.5)),
      category: e.entity_type || '未知',
      itemStyle: {
        color: entityColors[e.entity_type] || entityColors['未知'],
      },
      label: {
        show: degree >= labelThreshold || displayName.length <= 5,
        fontSize: totalNodes > 1000 ? 9 : 11,
        color: 'var(--color-text-primary)',
        formatter: (params) => {
          const name = params.data.name
          return name.length > 8 ? name.slice(0, 7) + '…' : name
        },
      },
      // 自定义数据（供 tooltip 和 click 使用）
      entityType: e.entity_type,
      subject: e.subject,
      grade: e.grade,
      description: e.description,
      fullName: e.name,  // 完整路径
      displayName: displayName,
    }
  })

  const links = relations.map(r => ({
    source: r.source,
    target: r.target,
    value: r.weight || 1,
    label: {
      show: false,
      formatter: r.relation || '相关',
      fontSize: 10,
      color: 'var(--color-text-tertiary)',
    },
    lineStyle: {
      width: Math.min(3, Math.max(1, (r.weight || 1))),
      curveness: 0.1,
      opacity: 0.5,
    },
  }))

  // 力导向布局：统一关闭动画 + 高摩擦快速收敛（防止拖拽/交互时力模拟重算导致卡顿）
  const isLarge = totalNodes > 2000
  const isMedium = totalNodes > 500
  const forceConfig = isLarge
    ? { repulsion: 60, gravity: 0.25, edgeLength: [20, 60], friction: 0.6, layoutAnimation: false }
    : isMedium
    ? { repulsion: 120, gravity: 0.15, edgeLength: [30, 70], friction: 0.6, layoutAnimation: false }
    : { repulsion: 200, gravity: 0.1, edgeLength: [40, 100], friction: 0.6, layoutAnimation: false }

  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'var(--color-surface)',
      borderColor: 'var(--color-border)',
      textStyle: { color: 'var(--color-text-primary)' },
      formatter: (params) => {
        if (params.dataType === 'node') {
          const d = params.data
          const parts = []
          parts.push(`<strong>${d.displayName || d.name}</strong>`)
          if (d.fullName && d.fullName !== d.displayName) {
            parts.push(`<span style="font-size:11px;color:#888">${d.fullName}</span>`)
          }
          parts.push(`类型: ${d.entityType || '未知'}`)
          if (d.subject) parts.push(`学科: ${d.subject}`)
          if (d.grade) parts.push(`学段: ${d.grade}`)
          parts.push(`关联数: ${d.value}`)
          return parts.join('<br/>')
        }
        return `${params.data.source} → ${params.data.target}`
      },
    },
    animationDuration: 500,
    animationEasingUpdate: 'quinticInOut',
    series: [{
      type: 'graph',
      layout: 'force',
      data: nodes,
      links: links,
      roam: true,         // 允许画布平移/缩放（不触发力重算）
      draggable: false,    // 禁止拖拽节点（拖拽会触发力模拟重算 → 卡顿根因）
      focusNodeAdjacency: true,
      large: isLarge || isMedium,
      force: forceConfig,
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3, opacity: 1 },
        itemStyle: { shadowBlur: 15, shadowColor: 'rgba(75, 94, 228, 0.4)' },
      },
      lineStyle: {
        color: 'source',
        curveness: 0.1,
      },
    }],
  }
}

// 学段变化时重置学科并重新获取该学段的学科列表
function onFilterChange() {
  filterSubject.value = ''
  fetchStats(filterGrade.value || undefined)
}

// 点击加载按钮
async function handleLoadClick() {
  if (!filterGrade.value || !filterSubject.value) return
  doLoad()
}

// 实际加载图谱数据
async function doLoad() {
  loading.value = true
  try {
    const res = await getKnowledgeGraphData(filterSubject.value || undefined, filterGrade.value || undefined)
    const entityCount = (res.entities || []).length

    if (entityCount === 0) {
      // 无数据：保持空状态，给用户明确提示
      rawData.value = null
      stats.value = res.stats || { entity_count: 0, relation_count: 0 }
      ElMessage.warning(`当前「${filterGrade.value} · ${filterSubject.value}」暂无知识图谱数据，请尝试其他学段或学科`)
      return
    }

    rawData.value = res
    stats.value = res.stats

    await nextTick()
    if (!chart.value && chartRef.value) {
      chart.value = echarts.init(chartRef.value, null, { renderer: 'canvas' })
      chart.value.on('click', handleNodeClick)
      window.addEventListener('resize', handleResize)
    }

    if (chart.value) {
      chart.value.setOption(buildChartOption(res), true)
    }
  } catch (e) {
    ElMessage.error('加载知识图谱失败')
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function handleNodeClick(params) {
  if (params.dataType !== 'node') return
  const name = params.data.fullName || params.data.name
  await focusEntity(name)
}

async function focusEntity(name) {
  try {
    const res = await getEntityDetail(encodeURIComponent(name))
    selectedEntity.value = res.entity
    neighbors.value = (res.neighbors || []).map(n => ({
      ...n,
      display_name: n.display_name || n.name,
    }))
  } catch (e) {
    ElMessage.error('获取实体详情失败')
  }
}

function handleResize() {
  chart.value?.resize()
}

onMounted(() => {
  fetchStats()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart.value?.dispose()
  chart.value = null
})
</script>

<style scoped>
.kg-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  max-width: 1400px;
  margin: 0 auto;
}

.kg-header {
  flex-shrink: 0;
}
.kg-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--color-text-primary);
  margin: 0;
}
.kg-subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin: var(--space-1) 0 0;
}

/* 统计卡片 */
.kg-stats {
  display: flex;
  gap: var(--space-4);
  flex-shrink: 0;
}
.stat-card {
  flex: 1;
  max-width: 200px;
  text-align: center;
  padding: var(--space-4) var(--space-5);
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  transition: all var(--transition-base);
}
.stat-card:hover {
  box-shadow: var(--shadow-floating);
  transform: translateY(-1px);
}
.stat-val {
  font-size: 28px;
  font-weight: var(--font-extrabold);
  line-height: 1.1;
}
.stat-lbl {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  font-weight: var(--font-medium);
  margin-top: 4px;
}

/* 筛选栏 */
.kg-filter {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}
.filter-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-left: var(--space-2);
}

.filter-hint-warn {
  color: #fa8c16 !important;
  font-weight: var(--font-medium);
}

/* 主内容区 */
.kg-main {
  flex: 1;
  display: flex;
  gap: var(--space-4);
  min-height: 0;
  overflow: hidden;
}

.kg-chart-wrap {
  flex: 1;
  min-width: 0;
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  overflow: hidden;
}
.kg-chart {
  width: 100%;
  height: 100%;
}

/* 空状态 */
.kg-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: var(--space-3);
}
.empty-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  margin: 0;
}
.empty-desc {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin: 0;
}

/* 详情面板 */
.kg-detail {
  width: 320px;
  flex-shrink: 0;
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-4) var(--space-2);
  border-bottom: 1px solid var(--color-border);
}
.detail-title {
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--color-text-primary);
  margin: 0;
  word-break: break-all;
}
.detail-close {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: all var(--transition-base);
}
.detail-close:hover {
  background: var(--color-bg);
  color: var(--color-text-primary);
}

.detail-path {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  background: var(--color-bg);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
  word-break: break-all;
}
.path-label {
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
}

.detail-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
}
.detail-tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.detail-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0 0 var(--space-3);
}

.detail-section {
  margin-top: var(--space-3);
}
.detail-section-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--space-2);
}

.neighbor-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.neighbor-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base);
  border-left: 3px solid transparent;
}
.neighbor-item:hover {
  background: var(--color-primary-light);
  border-left-color: var(--color-primary);
}
.neighbor-name {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  font-weight: var(--font-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.detail-empty {
  text-align: center;
  padding: var(--space-6) 0;
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

/* 滚动条 */
.detail-body::-webkit-scrollbar { width: 4px; }
.detail-body::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 10px;
}
</style>

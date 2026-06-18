<template>
  <!--
    KnowledgeView.vue — 管理端知识库管理（MD3 灵动风格）
    左侧知识库列表 + 右侧详情（文档表格 + 统计）
  -->
  <div class="kb-page">
    <h2 class="page-title"><el-icon :size="22"><Collection /></el-icon> 知识库管理</h2>

    <el-row :gutter="20">
      <!-- ===== 左侧：知识库列表 ===== -->
      <el-col :span="10">
        <div class="surface-card kb-list-card">
          <div class="card-header">
            <span class="card-title">📚 知识库列表</span>
            <button class="gradient-btn-sm" @click="showCreate = true">
              <el-icon :size="14"><Plus /></el-icon> 新建
            </button>
          </div>
          <div v-loading="loadingKBs" class="kb-list-body">
            <div
              v-for="kb in kbList" :key="kb.id"
              class="kb-item" :class="{ active: selectedKB?.id === kb.id }"
              @click="selectKB(kb)"
            >
              <div class="kb-item-icon">
                <el-icon :size="18"><Folder /></el-icon>
              </div>
              <div class="kb-item-info">
                <div class="kb-item-name">{{ kb.name }}</div>
                <div class="kb-item-meta">
                  <el-tag size="small" type="info" effect="light">{{ kb.doc_count || 0 }} 文档</el-tag>
                  <el-tag size="small" type="success" effect="light" class="ml-1">{{ kb.chunk_count || 0 }} 块</el-tag>
                </div>
              </div>
              <div class="kb-item-arrow">
                <el-icon :size="14"><ArrowRight /></el-icon>
              </div>
            </div>
            <el-empty v-if="!kbList.length && !loadingKBs" description="暂无知识库" :image-size="60" />
          </div>
        </div>
      </el-col>

      <!-- ===== 右侧：知识库详情 ===== -->
      <el-col :span="14">
        <div class="surface-card kb-detail-card" v-if="selectedKB">
          <div class="card-header">
            <span class="card-title">📖 {{ selectedKB.name }}</span>
            <button class="action-btn action-delete" title="删除知识库" @click="handleDeleteKB">
              <el-icon :size="16"><Delete /></el-icon>
            </button>
          </div>

          <!-- 统计小卡片 -->
          <div class="kb-stats" v-if="kbStats">
            <div class="kb-stat-item">
              <div class="stat-val" style="color:var(--color-primary)">{{ kbStats.doc_count || 0 }}</div>
              <div class="stat-lbl">文档数</div>
            </div>
            <div class="kb-stat-item">
              <div class="stat-val" style="color:var(--color-success)">{{ kbStats.chunk_count || 0 }}</div>
              <div class="stat-lbl">知识块</div>
            </div>
            <div class="kb-stat-item">
              <div class="stat-val" style="color:var(--color-warning)">{{ formatSize(kbStats.total_size) }}</div>
              <div class="stat-lbl">总大小</div>
            </div>
          </div>

          <el-divider />

          <!-- 文档列表 -->
          <div class="card-header sub-header">
            <span class="card-title">📄 知识库文档</span>
          </div>
          <el-table :data="kbDocs" stripe size="small" v-loading="loadingDocs" empty-text="暂无文档" class="styled-table">
            <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip />
            <el-table-column prop="file_type" label="类型" width="80" align="center">
              <template #default="{row}"><el-tag size="small" effect="light" round>{{ row.file_type }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="chunk_count" label="块数" width="60" align="center" />
            <el-table-column label="操作" width="100" align="center" fixed="right">
              <template #default="{row}">
                <button class="action-btn action-view" title="预览" @click="handlePreview(row)">
                  <el-icon :size="15"><View /></el-icon>
                </button>
                <el-popconfirm title="确定彻底删除文档？" @confirm="handleDeleteDoc(row)">
                  <template #reference>
                    <button class="action-btn action-delete" title="彻底删除">
                      <el-icon :size="15"><Delete /></el-icon>
                    </button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
          <!-- 分页 -->
          <div class="pagination-wrap" v-if="kbDocsTotal > pageSize">
            <el-pagination
              v-model:current-page="kbDocsPage" :page-size="pageSize" :total="kbDocsTotal"
              layout="prev, pager, next" @current-change="loadKBDocs" small background
            />
          </div>
        </div>

        <el-empty v-else description="请选择左侧知识库查看详情" :image-size="100" />
      </el-col>
    </el-row>

    <!-- ===== 新建知识库弹窗 ===== -->
    <el-dialog v-model="showCreate" title="新建知识库" width="420px" :close-on-click-modal="false">
      <el-form :model="createForm" label-width="60px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="请输入知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="3" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建</el-button>
      </template>
    </el-dialog>

    <!-- ===== 文档预览弹窗 ===== -->
    <el-dialog v-model="previewVisible" :title="previewTitle" width="75%" top="3vh" destroy-on-close class="preview-dialog">
      <div v-if="previewLoading" v-loading="previewLoading" style="min-height:200px"></div>
      <div v-else class="doc-preview-body">
        <div class="doc-preview-content" v-text="previewContent"></div>
      </div>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { listKB, createKB, getKB, deleteKB, getKBStats, getKBDocuments, deleteDocument, getDocument } from '@/api/admin'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Folder, ArrowRight, Delete, Collection, View } from '@element-plus/icons-vue'

const kbList = ref([])
const selectedKB = ref(null)
const loadingKBs = ref(false)
const loadingDocs = ref(false)
const kbStats = ref(null)
const kbDocs = ref([])
const kbDocsPage = ref(1)
const kbDocsTotal = ref(0)
const pageSize = ref(10)
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '' })
const previewVisible = ref(false)
const previewTitle = ref('')
const previewContent = ref('')
const previewLoading = ref(false)

function formatSize(bytes) {
  if (!bytes || bytes <= 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0; let val = bytes
  while (val >= 1024 && i < units.length - 1) { val /= 1024; i++ }
  return val.toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
}

async function loadKBs() {
  loadingKBs.value = true
  try {
    const res = await listKB()
    kbList.value = res.items || res.knowledge_bases || res.data || []
  } catch (_) {} finally { loadingKBs.value = false }
}

async function selectKB(kb) {
  selectedKB.value = kb; kbDocsPage.value = 1
  try { kbStats.value = await getKBStats(kb.id) } catch (_) { /* */ }
  loadKBDocs()
}

async function loadKBDocs() {
  if (!selectedKB.value) return
  loadingDocs.value = true
  try {
    const res = await getKBDocuments(selectedKB.value.id, kbDocsPage.value, pageSize.value)
    kbDocs.value = res.documents || []; kbDocsTotal.value = res.total || 0
  } catch (_) {} finally { loadingDocs.value = false }
}

async function handleCreate() {
  if (!createForm.value.name.trim()) { ElMessage.warning('请输入知识库名称'); return }
  creating.value = true
  try {
    await createKB({ name: createForm.value.name, description: createForm.value.description })
    ElMessage.success('创建成功')
    showCreate.value = false
    createForm.value = { name: '', description: '' }
    loadKBs()
  } catch (_) {} finally { creating.value = false }
}

async function handleDeleteKB() {
  try {
    await ElMessageBox.confirm(`确定删除知识库「${selectedKB.value.name}」？`, '警告', { type: 'warning' })
    await deleteKB(selectedKB.value.id)
    ElMessage.success('删除成功')
    selectedKB.value = null; kbStats.value = null; kbDocs.value = []
    loadKBs()
  } catch (_) { /* cancel or error */ }
}

async function handlePreview(row) {
  previewVisible.value = true
  previewTitle.value = row.filename || row.id
  previewLoading.value = true
  previewContent.value = ''
  try {
    const res = await getDocument(row.id)
    previewContent.value = res.content || '(文档内容为空)'
  } catch {
    previewContent.value = '(加载失败，请重试)'
  } finally {
    previewLoading.value = false
  }
}

async function handleDeleteDoc(row) {
  try {
    await deleteDocument(row.id)
    ElMessage.success('文档已彻底删除')
    loadKBDocs()
    loadKBs() // 刷新KB列表中的文档计数
  } catch (_) {}
}

onMounted(loadKBs)
</script>

<style scoped>
.kb-page { max-width: 1200px; margin: 0 auto; }

/* ===== 知识库列表 ===== */
.kb-list-card { height: calc(100vh - 120px); display: flex; flex-direction: column; }
.kb-list-body { flex: 1; overflow-y: auto; padding: var(--space-2) var(--space-4) var(--space-4); }
.kb-list-body::-webkit-scrollbar { width: 4px; }
.kb-list-body::-webkit-scrollbar-thumb { background: var(--color-text-disabled); border-radius: 10px; }

.kb-item {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-3) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base);
  border: 1px solid transparent;
  margin-bottom: var(--space-1);
}
.kb-item:hover { background: var(--color-primary-light); border-color: rgba(22,93,255,0.12); }
.kb-item.active {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(22,93,255,0.08);
}
.kb-item-icon {
  width: 36px; height: 36px;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-bg); color: var(--color-text-tertiary);
  flex-shrink: 0;
  transition: all var(--transition-base);
}
.kb-item.active .kb-item-icon { background: var(--color-primary); color: #fff; }
.kb-item-info { flex: 1; min-width: 0; }
.kb-item-name { font-weight: var(--font-semibold); font-size: var(--text-base); color: var(--color-text-primary); margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-item-meta { display: flex; gap: 4px; }
.kb-item-arrow { color: var(--color-text-disabled); transition: all var(--transition-base); }
.kb-item.active .kb-item-arrow { color: var(--color-primary); }
.ml-1 { margin-left: 4px; }

/* ===== 详情卡片 ===== */
.kb-detail-card { height: calc(100vh - 120px); display: flex; flex-direction: column; overflow-y: auto; }
.kb-stats {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3);
  padding: 0 var(--space-5);
}
.kb-stat-item {
  text-align: center; padding: var(--space-4);
  background: var(--color-bg); border-radius: var(--radius-md);
}
.stat-val { font-size: 24px; font-weight: var(--font-extrabold); line-height: 1.1; }
.stat-lbl { font-size: var(--text-xs); color: var(--color-text-tertiary); font-weight: var(--font-medium); margin-top: 2px; }
.sub-header { padding: var(--space-3) var(--space-5); background: transparent; border-bottom: none; }

/* 本地表格覆盖 */
.styled-table { flex: 1; }

.pagination-wrap { display: flex; justify-content: center; padding: var(--space-4); border-top: 1px solid var(--color-divider); }

/* 操作按钮 */
.action-btn {
  width: 28px; height: 28px;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; border-radius: var(--radius-sm);
  background: transparent; cursor: pointer;
  transition: all var(--transition-fast);
  margin: 0 2px;
}
.action-view { color: var(--color-primary); }
.action-view:hover { background: var(--color-primary-light); }
.action-delete { color: var(--color-danger); }
.action-delete:hover { background: rgba(245,63,63,0.1); }

/* 预览弹窗 */
.preview-dialog :deep(.el-dialog__body) { padding: var(--space-3) var(--space-5); }
.doc-preview-body { max-height: 70vh; overflow: auto; }
.doc-preview-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Consolas', 'Courier New', 'Noto Sans CJK SC', monospace;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-primary);
  background: var(--color-bg);
  padding: var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

/* 暗黑 */
html.dark .kb-item.active { background: rgba(22,93,255,0.12); }
html.dark .kb-stat-item { background: var(--color-surface-secondary); }
</style>

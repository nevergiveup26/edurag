<template>
  <!--
    UploadView.vue — 管理端文档上传（MD3 灵动风格）
    拖拽上传区域 + 上传进度 + 已上传文档表格
  -->
  <div class="upload-page">
    <h2 class="page-title"><el-icon :size="22"><UploadFilled /></el-icon> 文档上传</h2>

    <!-- ===== 知识库选择 ===== -->
    <div class="kb-select-row surface-card">
      <div class="kb-select-inner">
        <span class="kb-label">📁 目标知识库：</span>
        <el-select
          v-model="selectedKbId"
          placeholder="选择知识库（可选，不选则不上传至任何库）"
          clearable
          size="default"
          class="kb-select"
        >
          <el-option
            v-for="kb in kbList"
            :key="kb.kb_id || kb.id"
            :label="kb.name"
            :value="kb.kb_id || kb.id"
          >
            <span>{{ kb.name }}</span>
            <span class="kb-option-tag" v-if="kb.category">{{ kb.category }}</span>
          </el-option>
        </el-select>
      </div>
    </div>

    <!-- ===== 上传卡片 ===== -->
    <div class="surface-card">
      <div class="card-header">
        <span class="card-title">📤 上传文档</span>
      </div>
      <div class="upload-body">
        <!-- 拖拽区域 -->
        <el-upload
          ref="uploadRef"
          drag multiple
          :auto-upload="false"
          :on-change="handleChange"
          :before-remove="handleRemove"
          :file-list="fileList"
          accept=".pdf,.docx,.txt,.md,.html,.jpg,.jpeg,.png,.gif,.webp,.bmp"
          class="upload-dragger"
        >
          <div class="dragger-inner">
            <div class="dragger-icon">
              <el-icon :size="40"><UploadFilled /></el-icon>
            </div>
            <p class="dragger-text">拖拽文件到此处</p>
            <p class="dragger-hint">或 <em>点击选择文件</em></p>
          </div>
          <template #tip>
            <div class="dragger-tip">
              支持 PDF、DOCX、TXT、MD、HTML 及图片格式（JPG/PNG/GIF/WebP/BMP）
            </div>
          </template>
        </el-upload>

        <!-- 上传按钮 -->
        <div v-if="fileList.length > 0" class="submit-row">
          <button class="gradient-btn" :class="{ loading: uploading }" :disabled="uploading" @click="doUpload">
            <span v-if="uploading" class="btn-spinner"></span>
            <span v-else class="btn-content">
              <el-icon :size="16"><Upload /></el-icon>
              上传 {{ fileList.length }} 个文件
            </span>
          </button>
        </div>

        <!-- 上传结果 -->
        <div v-if="uploadResults.length > 0" class="results-area">
          <el-alert
            v-for="(r, i) in uploadResults" :key="i"
            :title="r.filename"
            :type="r.success ? 'success' : 'error'"
            :description="r.message"
            :closable="false" show-icon
            class="result-alert"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { uploadDocuments } from '@/api/index'
import { listKB } from '@/api/admin'
import { ElMessage } from 'element-plus'
import { UploadFilled, Upload } from '@element-plus/icons-vue'

const uploadRef = ref(null)
const fileList = ref([])
const uploading = ref(false)
const uploadResults = ref([])
const kbList = ref([])
const selectedKbId = ref('')

function handleChange(_f, files) { fileList.value = files }
function handleRemove(_f, files) { fileList.value = files }

async function doUpload() {
  if (!fileList.value.length) return
  uploading.value = true
  uploadResults.value = []
  const rawFiles = fileList.value.map(f => f.raw)
  try {
    const kbId = selectedKbId.value || null
    const res = await uploadDocuments(rawFiles, kbId)
    
    const skipped = res.skipped_duplicates || 0
    const dedupDetails = res.dedup_details || []
    const totalSubmitted = rawFiles.length
    const newUploaded = totalSubmitted - skipped
    
    // 构建去重详情映射（filename → 重复信息）
    const dedupByFilename = {}
    dedupDetails.forEach(d => { 
      if (d.filename) dedupByFilename[d.filename] = d 
    })

    // 为每个文件生成结果
    uploadResults.value = rawFiles.map(f => {
      const dup = dedupByFilename[f.name]
      if (dup) {
        return {
          filename: f.name,
          success: false,
          message: `已跳过 — 与已有文档「${dup.matched_title || dup.matched_doc_id}」完全重复 (MD5: ${dup.md5_hash?.slice(0,12)}...)`
        }
      }
      return {
        filename: f.name,
        success: true,
        message: kbId ? '上传成功（已关联知识库）' : '上传成功'
      }
    })
    
    // 如果有些去重详情没有匹配到文件名（fallback）
    const unmatchedDups = dedupDetails.filter(d => !d.filename || !rawFiles.some(f => f.name === d.filename))
    if (unmatchedDups.length > 0) {
      uploadResults.value.push(...unmatchedDups.map(d => ({
        filename: `⚠ 重复文档 (MD5: ${d.md5_hash?.slice(0,12)}...)`,
        success: false,
        message: `Tier${d.tier}: 与已有文档「${d.matched_title || d.matched_doc_id}」内容重复 — ${d.reason}`
      })))
    }

    // 显示结果消息
    if (skipped > 0 && newUploaded > 0) {
      ElMessage.warning(`检测到 ${skipped} 个重复文档已跳过，成功上传 ${newUploaded} 个文档`)
    } else if (skipped > 0) {
      ElMessage.warning(`所有 ${skipped} 个文档均已存在，已跳过`)
    } else if (newUploaded > 0) {
      ElMessage.success(`成功上传 ${newUploaded} 个文档`)
    }
    
    fileList.value = []
  } catch (e) {
    uploadResults.value = rawFiles.map(f => ({
      filename: f.name, success: false,
      message: e.response?.data?.detail || '上传失败',
    }))
  } finally { uploading.value = false }
}

async function fetchKBs() {
  try {
    const res = await listKB({ page_size: 100 })
    kbList.value = res.items || res.knowledge_bases || []
  } catch (_) { kbList.value = [] }
}

onMounted(fetchKBs)
</script>

<style scoped>
.upload-page { max-width: 1000px; margin: 0 auto; }

/* 知识库选择器 */
.kb-select-row { padding: var(--space-3) var(--space-5); margin-bottom: var(--space-3); }
.kb-select-inner { display: flex; align-items: center; gap: var(--space-3); }
.kb-label { font-size: var(--text-sm); font-weight: var(--font-medium); color: var(--color-text-secondary); white-space: nowrap; }
.kb-select { min-width: 320px; }
.kb-option-tag {
  font-size: var(--text-xs);
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 1px 6px; border-radius: 10px;
  margin-left: 6px;
}

/* 上传区 */
.upload-body { padding: var(--space-4) var(--space-5) var(--space-4); }
.upload-dragger :deep(.el-upload-dragger) {
  border: 2px dashed var(--color-border) !important;
  border-radius: var(--radius-lg) !important;
  background: var(--color-bg) !important;
  transition: all var(--transition-base) !important;
  height: auto !important; padding: var(--space-10) var(--space-5) !important;
}
.upload-dragger :deep(.el-upload-dragger:hover) {
  border-color: var(--color-primary) !important;
  background: var(--color-primary-bg) !important;
}
.upload-dragger :deep(.el-upload-dragger.is-dragover) {
  border-color: var(--color-primary) !important;
  background: var(--color-primary-light) !important;
  box-shadow: 0 0 0 4px rgba(22,93,255,0.06) inset !important;
}
.dragger-inner { text-align: center; }
.dragger-icon {
  color: var(--color-primary);
  margin-bottom: var(--space-3);
  display: inline-flex; align-items: center; justify-content: center;
  width: 72px; height: 72px;
  border-radius: 50%;
  background: var(--color-primary-light);
}
.dragger-text { font-size: var(--text-md); font-weight: var(--font-medium); color: var(--color-text-secondary); margin-bottom: var(--space-1); }
.dragger-hint { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.dragger-hint em { color: var(--color-primary); font-style: normal; font-weight: var(--font-semibold); }
.dragger-tip { margin-top: var(--space-3); font-size: var(--text-xs); color: var(--color-text-disabled); }

.submit-row { margin-top: var(--space-5); text-align: center; }

/* 上传结果 */
.results-area { margin-top: var(--space-4); }
.result-alert { margin-bottom: var(--space-2); border-radius: var(--radius-md) !important; }
</style>
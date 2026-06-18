<template>
  <!--
    PhotoSearchView.vue — 拍照搜题
    Deep Ink 设计系统：surface-card 面板 + 渐变按钮 + 设计令牌
    ～ 上传拍照 / 错题文本 → 知识库检索 → 智能解析答案
  -->
  <div class="ps-page">
    <!-- ====== 页面标题 ====== -->
    <div class="page-title">
      <el-icon :size="20"><Camera /></el-icon>
      <span>拍照搜题</span>
      <el-tag size="small" effect="plain" type="info" style="margin-left:auto;">支持图片上传与文字输入</el-tag>
    </div>

    <!-- ====== 上传 + 搜索面板 ====== -->
    <div class="surface-card" style="margin-bottom:var(--space-5);">
      <div class="card-header">
        <span class="card-title">📸 题目输入</span>
      </div>
      <div style="padding:var(--space-5);">
        <!-- 上传区域 -->
        <div class="upload-area" :class="{ 'has-file': previewUrl }" @click="triggerUpload" v-if="!previewUrl">
          <el-icon :size="36" class="upload-icon"><PictureFilled /></el-icon>
          <div class="upload-text">点击上传或拖拽题目图片至此</div>
          <div class="upload-hint">支持 JPG / PNG，单个文件不超过 10MB</div>
        </div>

        <!-- 已选文件预览 -->
        <div v-else class="preview-row">
          <div class="preview-img-wrap">
            <img :src="previewUrl" class="preview-img" />
            <button class="remove-btn" @click.stop="clearFile" title="移除图片"><el-icon :size="16"><Close /></el-icon></button>
          </div>
          <div class="preview-info">
            <div class="preview-name">{{ file?.name }}</div>
            <div class="preview-size">（{{ formatSize(file?.size) }}）</div>
            <button class="gradient-btn-sm" @click="search" :disabled="searching" style="margin-top:var(--space-3);">
              <span v-if="searching" class="btn-spinner-sm"></span>
              <el-icon v-else :size="14"><Search /></el-icon>
              {{ searching ? '识别中…' : '开始搜题' }}
            </button>
          </div>
        </div>

        <input ref="fileInput" type="file" accept="image/*" style="display:none;" @change="onFilePicked" />

        <!-- 分隔线 -->
        <el-divider><span class="divider-text">或者输入文字</span></el-divider>

        <!-- 文字输入 -->
        <el-input
          v-model="searchText"
          type="textarea"
          :rows="3"
          placeholder="输入题目文字描述，或粘贴错题内容…"
          @keydown.ctrl.enter="searchByText"
          clearable
        />
        <div class="text-actions">
          <span></span>
          <button class="gradient-btn-sm" @click="searchByText" :disabled="searching || !searchText.trim()">
            <span v-if="searching" class="btn-spinner-sm"></span>
            <el-icon v-else :size="14"><Search /></el-icon>
            {{ searching ? '搜索中…' : '文字搜题' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ====== 题目解析结果 ====== -->
    <div class="surface-card" v-if="analysis || searching">
      <div class="card-header">
        <span class="card-title">📖 题目解析</span>
      </div>
      <div style="padding:var(--space-4);">
        <div v-if="searching" class="searching-state">
          <el-icon :size="28" class="is-loading"><Loading /></el-icon>
          <span>{{ searchProgress }}</span>
        </div>

        <!-- OCR 提取文字展示 -->
        <div v-if="extractedText" class="ocr-text-block">
          <span class="result-label">OCR 识别结果</span>
          <div class="ocr-text markdown-body" v-html="renderMarkdown(extractedText)"></div>
        </div>

        <!-- LLM 解析 -->
        <div v-if="analysis" class="analysis-block">
          <div class="markdown-body" v-html="renderMarkdown(analysis)"></div>
        </div>
      </div>
    </div>

    <!-- ====== 联网搜索来源（折叠） ====== -->
    <div class="surface-card" v-if="webSources.length">
      <div class="card-header" style="cursor:pointer;" @click="showSources = !showSources">
        <span class="card-title">
          🌐 联网参考来源
          <el-tag size="small" effect="plain" style="margin-left:var(--space-2);">{{ webSources.length }} 条</el-tag>
        </span>
        <el-icon :size="16" class="collapse-arrow" :class="{ expanded: showSources }"><ArrowRight /></el-icon>
      </div>
      <el-collapse-transition>
        <div v-show="showSources" style="padding:var(--space-4);">
          <div v-for="(src, idx) in webSources" :key="idx" class="result-item">
            <div class="result-header">
              <span class="result-idx">#{{ idx + 1 }}</span>
              <a v-if="src.url" :href="src.url" target="_blank" class="source-link">{{ src.title || src.url }}</a>
              <span v-else>{{ src.title }}</span>
            </div>
            <div class="result-body">
              <div class="source-content">{{ src.content }}</div>
            </div>
          </div>
        </div>
      </el-collapse-transition>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { photoSearch } from '@/api/index'
import { ElMessage } from 'element-plus'
import { Camera, PictureFilled, Search, Close, Loading, ArrowRight } from '@element-plus/icons-vue'
import { marked } from 'marked'
import katex from 'katex'
import DOMPurify from 'dompurify'
import 'katex/dist/katex.min.css'

const fileInput = ref(null)
const file = ref(null)
const previewUrl = ref('')
const searchText = ref('')
const searching = ref(false)
const searchProgress = ref('正在智能检索…')
const analysis = ref('')
const extractedText = ref('')
const webSources = ref([])
const showSources = ref(false)

function triggerUpload() { fileInput.value?.click() }

function onFilePicked(e) {
  const f = e.target.files?.[0]
  if (!f) return
  if (!f.type.startsWith('image/')) { ElMessage.warning('仅支持图片文件'); return }
  file.value = f
  previewUrl.value = URL.createObjectURL(f)
}

function clearFile() {
  file.value = null
  previewUrl.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
  return bytes.toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
}

// 图片搜题
async function search() {
  if (!file.value) return
  await doPhotoSearch(file.value, '')
}

// 文字搜题
async function searchByText() {
  if (!searchText.value.trim()) return
  await doPhotoSearch(null, searchText.value.trim())
}

async function doPhotoSearch(fileObj, queryStr) {
  searching.value = true
  analysis.value = ''
  extractedText.value = ''
  webSources.value = []
  searchProgress.value = fileObj ? '正在 OCR 识别图片…' : '正在联网搜索…'

  try {
    // 进度模拟
    const progressTimer = setInterval(() => {
      if (searchProgress.value.includes('OCR')) searchProgress.value = '正在联网搜索相关题目…'
      else if (searchProgress.value.includes('联网搜索')) searchProgress.value = '正在生成解析…'
    }, 2000)

    const res = await photoSearch(fileObj, queryStr)
    clearInterval(progressTimer)

    extractedText.value = res.extracted_text || ''
    if (extractedText.value && !searchText.value) searchText.value = extractedText.value
    analysis.value = res.analysis || ''
    webSources.value = res.web_sources || []

    if (res.error) ElMessage.warning(res.error)
    else if (!analysis.value) ElMessage.info('未获得解析结果')
  } catch (e) {
    ElMessage.error('搜题失败，请重试')
    console.error('[photo-search]', e)
  } finally {
    searching.value = false
  }
}

function renderMarkdown(text) {
  if (!text) return ''
  let html = marked.parse(text || '')
  html = String(html)
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: true, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  html = html.replace(/\$([^$]+?)\$/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: false, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  html = html.replace(/(\\left[(\[\\|.]|\\right[)\]\\|.]|\\frac\{[^}]+\}\{[^}]+\}|\\sqrt(\[\d+\])?\{[^}]+\}|\\times|\\div|\\pm|\\mp|\\cdot|\\leq|\\geq|\\neq|\\approx|\\sim|\\infty|\\pi|\\alpha|\\beta|\\gamma|\\delta|\\theta|\\lambda|\\mu|\\sigma|\\sum|\\int|\\prod|\\lim|\\to|\\rightarrow|\\Rightarrow|\\Leftrightarrow|\\angle|\\triangle|\\parallel|\\perp|\\circ|\\degree|\\%|\\qquad|\\quad|\\big|\\Big|\\bigg|\\Bigg|\\overline\{[^}]+\}|\\underline\{[^}]+\}|\\hat\{[^}]+\}|\\bar\{[^}]+\}|\\vec\{[^}]+\}|\\dot\{[^}]+\}|\\ddot\{[^}]+\}|\\text\{[^}]*\}|\\textbf\{[^}]*\}|\\textit\{[^}]*\})/g, (m) => { try { return katex.renderToString(m, { displayMode: false, throwOnError: false }) } catch { return m } })
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] })
}
</script>

<style scoped>
.ps-page { max-width: 860px; margin: 0 auto; }

/* ===== 上传区域 ===== */
.upload-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10) var(--space-5);
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
  min-height: 180px;
}
.upload-area:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}
.upload-icon {
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-3);
  transition: color var(--transition-base);
}
.upload-area:hover .upload-icon { color: var(--color-primary); }
.upload-text {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
}
.upload-hint {
  font-size: var(--text-xs);
  color: var(--color-text-disabled);
  margin-top: var(--space-1);
}

/* 文件预览行 */
.preview-row {
  display: flex;
  gap: var(--space-5);
  align-items: flex-start;
}
.preview-img-wrap {
  position: relative;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--color-border);
}
.preview-img {
  width: 160px;
  height: 120px;
  object-fit: cover;
  display: block;
}
.remove-btn {
  position: absolute;
  top: 6px; right: 6px;
  width: 26px; height: 26px;
  border: none;
  border-radius: 50%;
  background: rgba(0,0,0,0.5);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition-fast);
}
.remove-btn:hover { background: var(--color-danger); }
.preview-info { flex: 1; }
.preview-name {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
}
.preview-size {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-top: 2px;
}

/* 文字搜索区 */
.divider-text {
  font-size: var(--text-xs);
  color: var(--color-text-disabled);
  font-weight: var(--font-medium);
}
.text-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: var(--space-4);
}
.kb-check {
  display: none;
}

/* ===== 搜索结果 ===== */
.result-count {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--font-medium);
}
.searching-state {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-8) 0;
  justify-content: center;
  color: var(--color-text-tertiary);
  font-size: var(--text-base);
}

.result-item {
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
  transition: all var(--transition-fast);
}
.result-item:last-child { margin-bottom: 0; }
.result-item:hover {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(75, 94, 228, 0.06);
}
.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-divider);
}
.result-idx {
  font-size: var(--text-xs);
  font-weight: var(--font-bold);
  color: var(--color-primary);
  font-family: var(--font-mono);
}
.result-score {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--font-medium);
  font-variant-numeric: tabular-nums;
}
.result-body { display: flex; flex-direction: column; gap: var(--space-3); }
.result-q, .result-a {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text-primary);
}
.result-label {
  display: inline-block;
  font-size: var(--text-xs);
  font-weight: var(--font-bold);
  color: #fff;
  background: var(--color-primary-gradient);
  padding: 2px 8px;
  border-radius: var(--radius-xs);
  margin-right: var(--space-2);
  vertical-align: middle;
  letter-spacing: 0.02em;
}
.result-a {
  color: var(--color-text-secondary);
  background: var(--color-surface-secondary);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  border-left: 3px solid var(--color-success);
}
.result-a :deep(p) { margin: 4px 0; }
.result-a :deep(pre) {
  background: #1C1A2E;
  color: #D0CFE0;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}
.result-a :deep(code) {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  background: var(--color-bg);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
}

/* 暗黑模式 */
html.dark .searching-state { color: var(--color-text-tertiary); }
html.dark .ocr-text { background: var(--color-surface-secondary); color: var(--color-text-primary); }
html.dark .result-a { background: var(--color-surface-secondary); }
html.dark .result-a :deep(pre) { background: #121117; color: #C8C6D8; }
html.dark .result-a :deep(code) { background: var(--color-surface-elevated); }

/* OCR 识别文字 */
.ocr-text-block {
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px dashed var(--color-border-light);
}
.ocr-text {
  margin-top: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
  border-left: 3px solid var(--color-warning);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  white-space: pre-wrap;
  word-break: break-all;
}

/* LLM 解析块 */
.analysis-block {
  padding: var(--space-4) var(--space-5);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-lg);
  border-left: 4px solid var(--color-success);
}
.analysis-block :deep(p) { margin: 6px 0; line-height: 1.8; }
.analysis-block :deep(h3), .analysis-block :deep(h4) { margin: 12px 0 6px; }
.analysis-block :deep(ul), .analysis-block :deep(ol) { padding-left: 1.5em; }

/* 联网来源链接 */
.source-link {
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 70%;
  display: inline-block;
}
.source-link:hover { text-decoration: underline; }
.source-content {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-normal);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 折叠箭头 */
.collapse-arrow {
  color: var(--color-text-tertiary);
  transition: transform var(--transition-base);
}
.collapse-arrow.expanded {
  transform: rotate(90deg);
}
</style>
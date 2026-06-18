<template>
  <!--
    AgentView.vue — Material Design 3 学生端主页面
    包含两个模式：
    1. 智能问答 (chat) - AI 学习助手
    2. 作业批改 (grade) - 提交题目进行AI批改
  -->
  <div class="agent-page">

    <!-- ===== 模式切换标签页（胶囊样式） ===== -->
    <div class="mode-tabs">
      <button class="mode-tab" :class="{ active: mode === 'chat' }" @click="mode = 'chat'">
        <el-icon><ChatDotRound /></el-icon>
        <span>💬 智能问答</span>
      </button>
      <button class="mode-tab" :class="{ active: mode === 'grade' }" @click="mode = 'grade'">
        <el-icon><Document /></el-icon>
        <span>📝 作业批改</span>
      </button>
    </div>

    <div class="agent-main">

        <!-- ============================ -->
        <!-- Mode 1: 智能问答             -->
        <!-- ============================ -->
        <template v-if="mode === 'chat'">
          <!-- 工具卡片 -->
          <!-- 省略了解 -->

          <!-- 对话卡片 -->
          <div class="surface-card chat-card">
        <div class="card-header">
          <span class="card-title">💬 对话</span>
          <span v-if="thinking" class="thinking-badge">
            <span class="pulse-dot"></span> 思考中...
          </span>
        </div>

        

        <div class="agent-messages" ref="msgContainer">
          <div v-if="!messages.length" class="empty-state">
            <div class="empty-icon">
              <el-icon :size="36"><ChatLineSquare /></el-icon>
            </div>
            <p class="empty-title">开始你的学习之旅</p>
            <p class="empty-desc">向 AI 学习助手提问，它会自动选择合适的工具来帮你解答</p>
          </div>
          <div v-for="(msg, i) in messages" :key="i" class="agent-msg" :class="'msg-' + msg.role">
            <div class="msg-role">{{ msg.role === 'user' ? '👤 你' : '🤖 AI助手' }}</div>

            <!-- 思考链展示 -->
            <div v-if="msg.thinkingChain?.length" class="thinking-chain">
              <div
                v-for="(tc, j) in msg.thinkingChain"
                :key="j"
                class="tc-item"
                :class="'tc-' + tc.type"
              >
                <span class="tc-icon">{{ tcIcon(tc.type) }}</span>
                <span class="tc-text">{{ tc.text }}</span>
              </div>
            </div>

            <!-- 回答内容 -->
            <div v-if="msg.content" class="msg-content" v-html="renderMd(msg.content)" />

            <!-- 打字光标 -->
            <span v-if="msg.status === 'answering'" class="typing-cursor">▊</span>

            <!-- 工具标签 -->
            <div v-if="msg.tools_used?.length" class="msg-tools">
              <el-tag v-for="t in msg.tools_used" :key="t" size="small" type="warning" effect="light">
                🔧 {{ t }}
              </el-tag>
            </div>
          </div>
        </div>
        <!-- 小工具按钮栏 -->
        <div class="toolbar-row">
          <button class="tool-chip" @click="handleTool('essay')">
            <span class="tool-chip-icon">📝</span>
            <span>写作文</span>
          </button>
          <button class="tool-chip" @click="handleTool('calculator')">
            <span class="tool-chip-icon">🔢</span>
            <span>计算器</span>
          </button>
          <button class="tool-chip" @click="handleTool('dictionary')">
            <span class="tool-chip-icon">📖</span>
            <span>查字典</span>
          </button>
          <button class="tool-chip" @click="handleTool('translate')">
            <span class="tool-chip-icon">🌐</span>
            <span>翻译</span>
          </button>
        </div>

        <!-- ===== 图片预览区 ===== -->
        <div v-if="imagePreviews.length" class="image-preview-row">
          <div
            v-for="(img, idx) in imagePreviews"
            :key="idx"
            class="image-preview-item"
          >
            <img :src="img.url" :alt="'图片' + (idx+1)" />
            <button class="img-remove-btn" @click="removeImage(idx)" title="删除">
              <el-icon :size="12"><Close /></el-icon>
            </button>
          </div>
        </div>

        <div class="agent-input-area">
          <el-input
            v-model="input"
            placeholder="问任何学习问题..."
            @keyup.enter.exact="handleSend"
            @paste="onPaste"
            :disabled="thinking"
            size="large"
            class="chat-input-filled"
          />
          <button class="tool-btn" title="上传图片" :disabled="thinking" @click="triggerImageUpload">
            <el-icon :size="20"><Picture /></el-icon>
          </button>
          <button
            class="voice-btn"
            :class="{ recording: isRecording }"
            :disabled="thinking"
            title="按住说话"
            @mousedown="startRecording"
            @mouseup="stopRecording"
            @mouseleave="stopRecording"
            @touchstart.prevent="startRecording"
            @touchend.prevent="stopRecording"
          >
            <el-icon :size="20"><Microphone /></el-icon>
          </button>
          <button
            class="send-btn"
            :disabled="(!input.trim() && !imagePreviews.length) || thinking"
            @click="handleSend"
          >
            <el-icon v-if="!thinking" :size="18"><Promotion /></el-icon>
            <span v-else class="btn-spinner-sm"></span>
          </button>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept="image/*"
          multiple
          style="display:none"
          @change="onFileSelected"
        />
      </div>
    </template>

    <!-- ============================ -->
    <!-- Mode 2: 作业批改             -->
    <!-- ============================ -->
    <template v-if="mode === 'grade'">
      <!-- ===== 批改结果区（页面顶端，批改完成后展示）===== -->
      <!-- 批改进度可视化面板（流式展示思考链） -->
      <div v-if="grading || gradeThinkingChain.length" class="surface-card grade-progress-card">
        <div class="card-header">
          <span class="card-title">🔍 批改进度</span>
          <el-tag v-if="grading" type="warning" size="small" effect="dark">批改中...</el-tag>
          <el-tag v-else type="success" size="small" effect="dark">完成</el-tag>
        </div>

        <!-- 手写动画 -->
        <div v-if="grading" class="writing-animation">
          <div class="writing-paper">
            <span class="writing-hand">✍️</span>
            <span class="ink-dot dot-1">·</span>
            <span class="ink-dot dot-2">·</span>
            <span class="ink-dot dot-3">·</span>
          </div>
          <span class="writing-hint">AI 正在批改中...</span>
        </div>

        <!-- 进度条 -->
        <div v-if="gradeProgress > 0" class="grade-progress-bar">
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: (gradeProgress * 100) + '%' }"></div>
          </div>
          <span class="progress-text">{{ Math.round(gradeProgress * 100) }}%</span>
        </div>

        <!-- 思考链 -->
        <div v-if="gradeThinkingChain.length" class="grade-think-chain">
          <div
            v-for="(item, i) in gradeThinkingChain"
            :key="i"
            class="gtc-item"
            :class="'gtc-' + item.type"
          >
            <span class="gtc-icon">{{ tcIcon(item.type) }}</span>
            <span class="gtc-text">{{ item.text }}</span>
          </div>
        </div>

        <!-- 流式输出内容（token） -->
        <div v-if="gradeStreamContent" class="grade-stream-output">
          <div class="stream-content" v-html="renderMd(gradeStreamContent)"></div>
          <span v-if="grading" class="stream-cursor">▌</span>
        </div>
      </div>

      <!-- 批改结果卡片 -->
      <div v-if="gradeResult" class="surface-card grade-result-card">
        <div class="card-header">
          <span class="card-title">📊 批改结果</span>
          <el-tag :type="gradeResult.score >= 60 ? 'success' : 'danger'" size="large" effect="dark">
            {{ gradeResult.score }}/{{ gradeResult.max_score }} 分
          </el-tag>
        </div>

        <p class="grade-feedback" v-if="gradeResult.feedback">{{ gradeResult.feedback }}</p>

        <!-- 分步评分 -->
        <div v-if="gradeResult.steps?.length" class="grade-section">
          <h4 class="section-title">📋 分步评分</h4>
          <div v-for="(s, i) in gradeResult.steps" :key="i" class="step-row">
            <span class="step-desc">{{ s.description || s.step }}</span>
            <div class="step-bar">
              <div
                class="step-fill"
                :class="{ 'fill-success': s.status === 'correct' || (s.score >= s.max * 0.7), 'fill-warning': s.status !== 'correct' && (s.score < s.max * 0.7) }"
                :style="{ width: ((s.score || s.student_score || 0) / (s.max || s.max_score || 1) * 100) + '%' }"
              ></div>
            </div>
            <span class="step-score">{{ s.score || s.student_score }}/{{ s.max || s.max_score }}</span>
            <span class="step-status" :class="s.status === 'correct' ? 'status-ok' : s.status === 'wrong' ? 'status-err' : 'status-warn'">
              {{ s.status === 'correct' ? '✓' : s.status === 'wrong' ? '✗' : '△' }}
            </span>
          </div>
        </div>

        <!-- 错误标注 -->
        <div v-if="gradeResult.highlights?.length" class="grade-section">
          <h4 class="section-title">🔍 错误标注</h4>
          <div v-for="(h, i) in gradeResult.highlights" :key="i" class="highlight-item">
            <div class="hl-badge" :class="h.error_type ? 'badge-error' : 'badge-polish'">
              {{ h.error_type || (h.improved ? '润色' : '注意') }}
            </div>
            <div class="hl-content">
              <div v-if="h.original" class="hl-original">{{ h.original.slice(0, 200) }}</div>
              <div v-if="h.correction || h.improved || h.correct_solution" class="hl-fix">
                → {{ (h.correction || h.improved || h.correct_solution || '').slice(0, 200) }}
              </div>
              <div v-if="h.explanation || h.feedback || h.reason" class="hl-reason">
                {{ h.explanation || h.feedback || h.reason }}
              </div>
            </div>
          </div>
        </div>

        <!-- 改进建议 -->
        <div v-if="gradeResult.suggestions?.length" class="grade-section">
          <h4 class="section-title">💡 改进建议</h4>
          <ul class="suggestion-list">
            <li v-for="(s, i) in gradeResult.suggestions" :key="i">
              {{ typeof s === 'string' ? s : (s.reason || s.point || JSON.stringify(s)) }}
            </li>
          </ul>
        </div>

        <el-alert
          v-if="gradeResult.score < 60"
          title="此错题已自动收录到错题集 📒"
          type="warning"
          :closable="false"
          show-icon
          class="auto-save-alert"
        />
      </div>

      <!-- ===== 输入区（下方）===== -->
      <!-- Layer 1: 题目内容卡片 -->
      <div class="surface-card">
        <div class="card-header">
          <span class="card-title">📝 题目内容</span>
        </div>
        <div class="grade-input-group">
          <label class="float-label">
            <span class="float-label-text">输入题目</span>
            <el-input
              v-model="gradeForm.question"
              type="textarea"
              :rows="5"
              placeholder="请输入或拍照上传题目内容..."
              resize="vertical"
              class="grade-textarea"
            />
          </label>
          <div class="upload-actions">
            <label class="upload-btn" title="拍照上传题目">
              <el-icon :size="20"><Camera /></el-icon>
              <span>拍照</span>
              <input type="file" accept=".jpg,.jpeg,.png,.gif,.webp,.bmp" hidden @change="(e) => handleGradeImg(e, 'question')" />
            </label>
          </div>
        </div>
        <div v-if="questionImg" class="img-preview-row">
          <img :src="questionImg" class="preview-thumb" />
          <button class="remove-img-btn" @click="questionImg = ''" title="移除图片">
            <el-icon :size="14"><Close /></el-icon>
          </button>
        </div>
      </div>

      <!-- Layer 2: 作答内容卡片 -->
      <div class="surface-card">
        <div class="card-header">
          <span class="card-title">✏️ 我的作答</span>
        </div>
        <div class="grade-input-group">
          <label class="float-label">
            <span class="float-label-text">输入你的答案</span>
            <el-input
              v-model="gradeForm.user_answer"
              type="textarea"
              :rows="8"
              placeholder="请在这里输入你的作答..."
              resize="vertical"
              class="grade-textarea"
            />
          </label>
          <div class="upload-actions">
            <label class="upload-btn" title="拍照上传作答">
              <el-icon :size="20"><Camera /></el-icon>
              <span>拍照</span>
              <input type="file" accept=".jpg,.jpeg,.png,.gif,.webp,.bmp" hidden @change="(e) => handleGradeImg(e, 'answer')" />
            </label>
          </div>
        </div>
        <div v-if="answerImg" class="img-preview-row">
          <img :src="answerImg" class="preview-thumb" />
          <button class="remove-img-btn" @click="answerImg = ''" title="移除图片">
            <el-icon :size="14"><Close /></el-icon>
          </button>
        </div>
      </div>

      <!-- 提交按钮 -->
      <div class="submit-row">
        <button
          class="grade-submit-btn"
          :class="{ loading: grading }"
          :disabled="!canGrade"
          @click="doGrade"
        >
          <span v-if="grading" class="btn-spinner"></span>
          <span v-else class="btn-content">
            <el-icon :size="18"><Finished /></el-icon>
            提交批改
          </span>
        </button>
      </div>
    </template>
    </div> <!-- agent-main -->
</div> <!-- agent-page -->
</template>

<script setup>
/**
 * AgentView.vue — 学生端主页面逻辑
 * - chat 模式：AI 学习助手问答（SSE 流式输出 + 思考链）
 * - grade 模式：作业批改（含图片上传、分步评分、错误标注）
 */
import { ref, computed, onMounted, nextTick, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { connectAgentSSE, getStudentAgentTools, submitGrading, getConversation, connectGradeSSE, voiceToText } from '@/api/index'
import { ElMessage } from 'element-plus'
import {
  Promotion, Cpu, Finished, Camera, Picture, Microphone,
  ChatDotRound, Document, ChatLineSquare, Check, Close
} from '@element-plus/icons-vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import katex from 'katex'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'
import 'katex/dist/katex.min.css'


marked.setOptions({
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value
    return hljs.highlightAuto(code).value
  },
})

function renderMd(text) {
  if (!text) return ''
  let html = marked(text)
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: true, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  html = html.replace(/\$([^$]+?)\$/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: false, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  html = html.replace(/(\\left[(\[\\|.]|\\right[)\]\\|.]|\\frac\{[^}]+\}\{[^}]+\}|\\sqrt(\[\d+\])?\{[^}]+\}|\\times|\\div|\\pm|\\mp|\\cdot|\\leq|\\geq|\\neq|\\approx|\\sim|\\infty|\\pi|\\alpha|\\beta|\\gamma|\\delta|\\theta|\\lambda|\\mu|\\sigma|\\sum|\\int|\\prod|\\lim|\\to|\\rightarrow|\\Rightarrow|\\Leftrightarrow|\\angle|\\triangle|\\parallel|\\perp|\\circ|\\degree|\\%|\\qquad|\\quad|\\big|\\Big|\\bigg|\\Bigg|\\overline\{[^}]+\}|\\underline\{[^}]+\}|\\hat\{[^}]+\}|\\bar\{[^}]+\}|\\vec\{[^}]+\}|\\dot\{[^}]+\}|\\ddot\{[^}]+\}|\\text\{[^}]*\}|\\textbf\{[^}]*\}|\\textit\{[^}]*\})/g, (m) => { try { return katex.renderToString(m, { displayMode: false, throwOnError: false }) } catch { return m } })
  html = html.replace(/\\\(([\s\S]*?)\\\)/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: false, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  html = html.replace(/\\\[([\s\S]*?)\\\]/g, (_, l) => { try { return katex.renderToString(l.trim(), { displayMode: true, throwOnError: false }) } catch { return `<code>${_}</code>` } })
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] })
}

// ===== 公共状态 =====
const route = useRoute()
const mode = ref('chat')

// ===== QA 模式 =====
const tools = ref([])
const input = ref('')
const thinking = ref(false)
const messages = ref([])
const msgContainer = ref(null)
const activeStream = ref(null)  // 当前活跃的 SSE 连接
const conversationId = ref(null)  // 当前会话ID，首次对话后赋值

// ===== 图片上传 =====
const fileInput = ref(null)
const imagePreviews = ref([])  // [{ url, base64 }]

function triggerImageUpload() {
  fileInput.value?.click()
}

function onFileSelected(e) {
  const files = Array.from(e.target.files || [])
  for (const file of files) {
    if (file.size > 10 * 1024 * 1024) {
      ElMessage.warning('图片大小不能超过 10MB')
      continue
    }
    const reader = new FileReader()
    reader.onload = (ev) => {
      imagePreviews.value.push({ url: ev.target.result, base64: ev.target.result })
    }
    reader.readAsDataURL(file)
  }
  fileInput.value.value = ''
}

function onPaste(e) {
  const items = e.clipboardData?.items || []
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file.size > 10 * 1024 * 1024) {
        ElMessage.warning('图片大小不能超过 10MB')
        continue
      }
      const reader = new FileReader()
      reader.onload = (ev) => {
        imagePreviews.value.push({ url: ev.target.result, base64: ev.target.result })
      }
      reader.readAsDataURL(file)
    }
  }
}

function removeImage(idx) {
  imagePreviews.value.splice(idx, 1)
}

// ===== 语音输入 =====
const isRecording = ref(false)
let mediaRecorder = null
let audioChunks = []

async function startRecording() {
  if (thinking.value) return
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
    audioChunks = []
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data) }
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop())
      if (audioChunks.length === 0) return
      const blob = new Blob(audioChunks, { type: 'audio/webm' })
      // 录音太短（< 1秒）忽略
      if (blob.size < 500) {
        ElMessage.warning('录音太短，请重试')
        return
      }
      try {
        const res = await voiceToText(blob)
        if (res.text) {
          input.value = input.value ? input.value + ' ' + res.text : res.text
          // 自动发送
          await nextTick()
          handleSend()
        } else {
          ElMessage.warning('未识别到语音内容')
        }
      } catch (e) {
        ElMessage.error('语音识别失败: ' + (e.response?.data?.detail || e.message))
      }
    }
    mediaRecorder.start()
    isRecording.value = true
  } catch (e) {
    ElMessage.error('无法访问麦克风: ' + e.message)
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording.value) {
    mediaRecorder.stop()
    isRecording.value = false
  }
}

/** 思考链图标映射 */
function tcIcon(type) {
  const map = {
    thinking: '💭', action: '🔧', observation: '👁️',
    reflection: '🔄', reasoning: '💡', status: '⏳',
    token: '', done: '', start: '', error: '❌',
    tool_call: '🔧', tool_result: '📋',
  }
  return map[type] || '•'
}

async function loadTools() {
  try {
    const res = await getStudentAgentTools()
    tools.value = res.tools || []
  } catch (_) { /* skip */ }
}

function handleTool(type) {
  // 后端逻辑暂未实现，仅做 UI 展示
  const prompts = {
    essay: '请帮我写一篇作文，题目是：',
    calculator: '请帮我计算：',
    dictionary: '请帮我查一下：',
    translate: '请帮我翻译：',
  }
  input.value = prompts[type] || ''
}

function scrollBottom() {
  nextTick(() => {
    if (msgContainer.value) msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  })
}

async function handleSend() {
  const text = input.value.trim()
  const hasImages = imagePreviews.value.length > 0
  if (!text && !hasImages || thinking.value) return

  // 关闭上一个流（如果还在跑）
  if (activeStream.value) {
    activeStream.value.close()
    activeStream.value = null
  }

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  imagePreviews.value = []
  thinking.value = true
  scrollBottom()

  // 创建空的助理消息（流式填充）
  const msgIdx = messages.value.length
  messages.value.push({
    role: 'assistant',
    content: '',
    status: 'thinking',
    thinkingChain: [],
    tools_used: [],
  })
  scrollBottom()

  // 连接 SSE 流
  const stream = connectAgentSSE(
    { query: text, conversation_id: conversationId.value, images: imagePreviews.value.map(i => i.base64) },
    // onEvent
    (type, data) => {
      const msg = messages.value[msgIdx]
      if (!msg) return

      switch (type) {
        case 'thinking':
        case 'observation':
        case 'reflection':
        case 'reasoning':
        case 'status':
          // 添加到思考链（去重 + 限制条数）
          if (msg.thinkingChain.length < 30) {
            const text = data.content || data.text || data.thought || data.message || data.result || ''
            if (text && text !== msg.thinkingChain[msg.thinkingChain.length - 1]?.text) {
              msg.thinkingChain.push({ type, text: text.slice(0, 120) })
            }
          }
          break

        case 'action':
          // action: 记录工具名，构造显示文本
          if (msg.thinkingChain.length < 30) {
            const toolName = data.tool || ''
            const actionText = toolName ? `调用工具: ${toolName}` : (data.content || data.text || '')
            if (actionText && actionText !== msg.thinkingChain[msg.thinkingChain.length - 1]?.text) {
              msg.thinkingChain.push({ type, text: actionText.slice(0, 120) })
            }
            if (toolName && !msg.tools_used.includes(toolName)) {
              msg.tools_used.push(toolName)
            }
          }
          break

        case 'token':
          // 逐字追加到 content（后端用 content 字段）
          msg.status = 'answering'
          msg.content += (data.content || data.text || '')
          break

        case 'done':
          msg.status = 'done'
          thinking.value = false
          activeStream.value = null
          // 捕获会话ID以便后续对话复用
          if (data.conversation_id) {
            conversationId.value = data.conversation_id
          }
          break

        case 'error':
          msg.status = 'done'
          msg.content = msg.content || ('❌ ' + (data.content || data.message || '请求失败'))
          thinking.value = false
          activeStream.value = null
          break
      }
      scrollBottom()
    },
    // onError
    (err) => {
      const msg = messages.value[msgIdx]
      if (msg) {
        msg.content = msg.content || ('❌ ' + err)
        msg.status = 'done'
      }
      thinking.value = false
      activeStream.value = null
      scrollBottom()
    },
    // onDone
    () => {
      const msg = messages.value[msgIdx]
      if (msg) msg.status = 'done'
      thinking.value = false
      activeStream.value = null
      scrollBottom()
    }
  )

  activeStream.value = stream
}

// ===== 批改模式 =====
const grading = ref(false)
const gradeResult = ref(null)
const questionImg = ref('')
const answerImg = ref('')
const gradeForm = ref({
  question: '',
  user_answer: '',
})

// 流式批改进度
const gradeProgress = ref(0)
const gradeThinkingChain = ref([])
const gradeStreamContent = ref('')
const activeGradeStream = ref(null)

const canGrade = computed(() => {
  const hasQ = gradeForm.value.question.trim() || questionImg.value
  const hasA = gradeForm.value.user_answer.trim() || answerImg.value
  return hasQ && hasA && !grading.value
})

function resetGradeResult() {
  gradeResult.value = null
  gradeThinkingChain.value = []
  gradeStreamContent.value = ''
  gradeProgress.value = 0
}

const MAX_IMG_SIZE = 5 * 1024 * 1024  // 5MB
const ALLOWED_IMG_TYPES = ['image/jpeg', 'image/png', 'image/webp']

function handleGradeImg(e, type) {
  const file = e.target.files?.[0]
  if (!file) return

  if (!ALLOWED_IMG_TYPES.includes(file.type)) {
    ElMessage.warning('仅支持 JPG、PNG、WebP 格式的图片')
    return
  }
  if (file.size > MAX_IMG_SIZE) {
    ElMessage.warning('图片大小不能超过 5MB')
    return
  }

  const reader = new FileReader()
  reader.onload = (ev) => {
    if (type === 'question') questionImg.value = ev.target.result
    else answerImg.value = ev.target.result
  }
  reader.readAsDataURL(file)
}

async function doGrade() {
  if (!canGrade.value) return

  // 关闭上一个流
  if (activeGradeStream.value) {
    activeGradeStream.value.close()
    activeGradeStream.value = null
  }

  grading.value = true
  gradeResult.value = null
  gradeThinkingChain.value = []
  gradeStreamContent.value = ''
  gradeProgress.value = 0

  const payload = {
    question: gradeForm.value.question.trim(),
    user_answer: gradeForm.value.user_answer.trim(),
    auto_save: true,
  }
  if (questionImg.value) payload.question_image = questionImg.value
  if (answerImg.value) payload.answer_image = answerImg.value

  const stream = connectGradeSSE(
    payload,
    // onEvent
    (type, data) => {
      switch (type) {
        case 'status':
          gradeThinkingChain.value.push({ type: 'status', text: data.content || data.message || '' })
          break

        case 'thinking':
          gradeThinkingChain.value.push({ type: 'thinking', text: data.content || '' })
          break

        case 'action':
          const toolName = data.tool || ''
          const actionText = toolName ? `调用: ${toolName}` : (data.content || '')
          gradeThinkingChain.value.push({ type: 'action', text: actionText })
          break

        case 'observation':
          const obsText = data.content || ''
          if (obsText && obsText.length > 200) {
            gradeThinkingChain.value.push({ type: 'observation', text: obsText.slice(0, 200) + '...' })
          } else if (obsText) {
            gradeThinkingChain.value.push({ type: 'observation', text: obsText })
          }
          break

        case 'progress':
          gradeProgress.value = data.percent || 0
          if (data.content) {
            gradeThinkingChain.value.push({ type: 'status', text: data.content })
          }
          break

        case 'token':
          gradeStreamContent.value += (data.content || '')
          break

        case 'done':
          grading.value = false
          gradeProgress.value = 1.0
          activeGradeStream.value = null
          break

        case 'grading_result':
          // 解析结构化批改结果
          if (data.grading && Object.keys(data.grading).length) {
            gradeResult.value = data.grading
          }
          if (data.auto_saved) ElMessage.success('错题已自动收录')
          break

        case 'error':
          grading.value = false
          activeGradeStream.value = null
          ElMessage.error(data.content || '批改失败')
          break
      }
    },
    // onError
    (err) => {
      grading.value = false
      activeGradeStream.value = null
      ElMessage.error(err)
    },
    // onDone
    () => {
      grading.value = false
      activeGradeStream.value = null
    }
  )

  activeGradeStream.value = stream
}

async function loadConversationMessages(convId) {
  if (!convId) return
  // 关闭当前流
  if (activeStream.value) { activeStream.value.close(); activeStream.value = null }
  messages.value = []
  conversationId.value = convId
  input.value = ''
  try {
    const res = await getConversation(convId)
    const historyMsgs = res.messages || []
    if (historyMsgs.length) {
      messages.value = historyMsgs.map(m => ({
        role: m.role,
        content: m.content,
        status: 'done',
        thinkingChain: [],
        tools_used: [],
      }))
    }
    scrollBottom()
  } catch (_) {
    ElMessage.warning('加载历史消息失败')
  }
}

onMounted(async () => {
  await loadTools()
  const convId = route.query.conversation_id
  if (convId) await loadConversationMessages(convId)
})

// 从侧栏历史会话点击时，同一路由只变 query，需 watch
watch(() => route.query.conversation_id, (newId) => {
  if (newId && newId !== conversationId.value) {
    loadConversationMessages(newId)
  }
})

// 组件卸载时关闭流
onBeforeUnmount(() => {
  if (activeStream.value) {
    activeStream.value.close()
  }
  if (activeGradeStream.value) {
    activeGradeStream.value.close()
  }
})
</script>

<style scoped>
/* ================================================================
   AgentView.vue — MD3 学生端主页样式
   设计要点：
   - 胶囊式模式切换标签页（圆角 + 阴影）
   - 分层 surface-card 设计（Layer 1-3 深度递增）
   - 浮动标签 float-label 效果
   - 拍照上传按钮含图标 + 微动效
   - 渐变提交按钮 + 旋转加载动画
   - 0.25s ease-in-out 全局过渡
   ================================================================ */

.agent-page { display: flex; flex-direction: column; height: 100%; background: var(--color-bg); }

.agent-main {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5);
  width: 100%;
  max-width: 1000px;
  margin: 0 auto;
}

/* ----- 模式切换胶囊标签页 ----- */
.mode-tabs {
  display: flex;
  background: var(--color-bg);
  border-radius: var(--radius-xl);
  padding: 4px;
  margin-bottom: var(--space-5);
  gap: 4px;
  box-shadow: var(--shadow-card);
}

.mode-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 42px;
  border: none;
  background: transparent;
  border-radius: var(--radius-lg);
  font-family: var(--font-family-base);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
}
.mode-tab:hover {
  color: var(--color-text-primary);
  background: rgba(22, 93, 255, 0.04);
}
.mode-tab.active {
  background: var(--color-surface);
  color: var(--color-primary);
  font-weight: var(--font-semibold);
  box-shadow: var(--shadow-card);
}

/* ----- 分层卡片（surface-card） ----- */
.surface-card {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-4);
  overflow: hidden;
  transition: box-shadow var(--transition-base);
}
.surface-card:hover {
  box-shadow: var(--shadow-floating);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-divider);
  background: var(--color-surface-secondary);
}

.card-title {
  font-weight: var(--font-semibold);
  font-size: var(--text-base);
  color: var(--color-text-primary);
}

/* ===== QA 聊天 ===== */
.tools-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-5);
  min-height: 40px;
}

.tool-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-full);
  background: var(--color-success-light);
  color: var(--color-success);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  transition: all var(--transition-base);
}
.tool-chip:hover {
  background: var(--color-success);
  color: #fff;
  transform: translateY(-1px);
}

.agent-messages {
  max-height: 520px;
  overflow-y: auto;
  padding: var(--space-4) var(--space-5);
}

.agent-msg {
  margin-bottom: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  line-height: var(--leading-relaxed);
  animation: msg-in 0.3s var(--easing-emphasized);
}
@keyframes msg-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg-user {
  background: var(--color-primary-light);
  border: 1px solid rgba(22, 93, 255, 0.1);
}
.msg-assistant {
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
}
.msg-role { font-weight: var(--font-semibold); margin-bottom: 6px; font-size: var(--text-sm); }
.msg-content { font-size: var(--text-base); line-height: var(--leading-relaxed); }
.msg-content :deep(p) { margin: 6px 0; }
.msg-content :deep(pre) {
  background: #1e1e1e; color: #d4d4d4;
  padding: 12px 16px; border-radius: var(--radius-md);
  overflow-x: auto; font-size: var(--text-sm); line-height: 1.6;
}
.msg-content :deep(code) { font-size: var(--text-sm); }
.msg-tools { margin-top: var(--space-2); display: flex; flex-wrap: wrap; gap: 4px; }

/* 小工具按钮栏 */
.toolbar-row {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-5);
  flex-wrap: wrap;
}

.toolbar-row .tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-family: var(--font-family-base);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.toolbar-row .tool-chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
  transform: translateY(-1px);
}
.toolbar-row .tool-chip:active {
  transform: translateY(0);
}
.tool-chip-icon {
  font-size: 14px;
}

.agent-input-area {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5) var(--space-4);
  border-top: 1px solid var(--color-divider);
  align-items: center;
}
.chat-input-filled :deep(.el-input__wrapper) {
  background: var(--color-bg) !important;
  border-radius: var(--radius-md) !important;
  box-shadow: none !important;
}
.chat-input-filled :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--color-primary) inset !important;
  background: var(--color-surface) !important;
}

.send-btn {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: #fff;
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--transition-base);
}
.send-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
  box-shadow: 0 2px 12px rgba(22, 93, 255, 0.3);
  transform: scale(1.05);
}
.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

/* 思考链展示 */
.thinking-chain {
  margin-bottom: 8px;
  padding: 4px 0;
}
.tc-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  line-height: 1.4;
  padding: 4px 6px;
  margin: 2px 0;
  border-radius: 4px;
  color: var(--color-text-tertiary);
  background: rgba(100, 100, 150, 0.05);
}
.tc-thinking { background: rgba(59, 130, 246, 0.05); }
.tc-action { background: rgba(245, 158, 11, 0.05); color: var(--color-warning); }
.tc-observation { background: rgba(101, 163, 13, 0.05); }
.tc-reflection { background: rgba(156, 39, 176, 0.05); }
.tc-reasoning { background: rgba(16, 185, 129, 0.05); }
.tc-status { background: rgba(148, 163, 184, 0.05); }
.tc-icon { font-size: 14px; }
.tc-text { word-break: break-word; }

/* 打字光标 */
.typing-cursor {
  display: inline-block;
  width: 8px;
  height: 16px;
  margin-left: 2px;
  background: var(--color-primary);
  animation: cursor-blink 1s infinite;
  opacity: 1;
}
@keyframes cursor-blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* 标题上的思考气泡 */
.thinking-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-primary);
}
.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-primary);
  animation: dot-pulse 1.5s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1.2); }
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: var(--space-10) var(--space-5);
}
.empty-icon {
  color: var(--color-text-disabled);
  margin-bottom: var(--space-3);
}
.empty-title {
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}
.empty-desc {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  line-height: var(--leading-relaxed);
  max-width: 320px;
  margin: 0 auto;
}

/* ===== 批改模式 ===== */

/* 浮动标签 */
.grade-input-group {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5) var(--space-4);
  align-items: flex-start;
}

.float-label {
  flex: 1;
  position: relative;
}
.float-label-text {
  display: block;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: var(--space-2);
}

.grade-textarea :deep(.el-textarea__inner) {
  background: var(--color-bg) !important;
  border: 1px solid var(--color-border) !important;
  border-radius: var(--radius-md) !important;
  font-family: var(--font-family-base);
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  transition: all var(--transition-base);
  resize: vertical;
  color: var(--color-text-primary);
}
.grade-textarea :deep(.el-textarea__inner:focus) {
  background: var(--color-surface) !important;
  border-color: var(--color-primary) !important;
  box-shadow: 0 0 0 3px rgba(22, 93, 255, 0.1) !important;
}

/* 拍照上传按钮 */
.upload-actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: 22px;
}
.upload-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 80px;
  height: 80px;
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-secondary);
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  cursor: pointer;
  gap: 4px;
  transition: all var(--transition-base);
}
.upload-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
  transform: translateY(-2px);
  box-shadow: 0 2px 8px rgba(22, 93, 255, 0.12);
}

/* 图片预览 */
.img-preview-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: 0 var(--space-5) var(--space-4);
}
.preview-thumb {
  max-width: 180px;
  max-height: 120px;
  border-radius: var(--radius-md);
  border: 2px solid var(--color-border);
  object-fit: contain;
}
.remove-img-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-danger);
  color: #fff;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.remove-img-btn:hover {
  transform: scale(1.15);
  box-shadow: 0 2px 6px rgba(245, 63, 63, 0.3);
}

/* 提交按钮 */
.submit-row {
  padding: var(--space-2) 0 var(--space-4);
  text-align: center;
}

.grade-submit-btn {
  min-width: 200px;
  height: 48px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), #4080FF);
  color: #fff;
  font-family: var(--font-family-base);
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  cursor: pointer;
  padding: 0 var(--space-8);
  transition: all var(--transition-base);
  position: relative;
  overflow: hidden;
}
.grade-submit-btn::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.12) 50%, rgba(255,255,255,0) 100%);
  transform: translateX(-100%);
  transition: transform 0.6s ease;
}
.grade-submit-btn:hover:not(:disabled)::after {
  transform: translateX(100%);
}
.grade-submit-btn:hover:not(:disabled) {
  box-shadow: 0 4px 24px rgba(22, 93, 255, 0.4);
  transform: translateY(-2px);
}
.grade-submit-btn:active:not(:disabled) {
  transform: translateY(0);
}
.grade-submit-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 手写批改动画 */
.writing-animation {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) 0;
}
.writing-paper {
  position: relative;
  width: 180px;
  height: 48px;
  background: linear-gradient(to bottom, transparent 0, transparent 22px, var(--color-divider) 22px, var(--color-divider) 23px, transparent 23px, transparent 45px, var(--color-divider) 45px, var(--color-divider) 46px);
  border-radius: 4px;
  overflow: hidden;
}
.writing-hand {
  position: absolute;
  top: -2px;
  left: 0;
  font-size: 28px;
  animation: write-move 2.4s ease-in-out infinite;
  filter: drop-shadow(0 1px 2px rgba(0,0,0,0.15));
  z-index: 2;
}
.ink-dot {
  position: absolute;
  top: 17px;
  font-size: 18px;
  font-weight: bold;
  color: var(--color-primary);
  opacity: 0;
  z-index: 1;
}
.dot-1 { left: 40px;  animation: ink-appear 2.4s ease-in-out infinite; }
.dot-2 { left: 80px;  animation: ink-appear 2.4s ease-in-out 0.4s infinite; }
.dot-3 { left: 120px; animation: ink-appear 2.4s ease-in-out 0.8s infinite; }

@keyframes write-move {
  0%   { transform: translateX(0px) rotate(-2deg); }
  15%  { transform: translateX(30px) rotate(0deg); }
  30%  { transform: translateX(60px) rotate(2deg); }
  45%  { transform: translateX(90px) rotate(0deg); }
  60%  { transform: translateX(120px) rotate(-1deg); }
  75%  { transform: translateX(145px) rotate(1deg); }
  90%  { transform: translateX(155px) rotate(0deg); }
  100% { transform: translateX(0px) rotate(-2deg); }
}
@keyframes ink-appear {
  0%   { opacity: 0; transform: scale(0.3); }
  10%  { opacity: 0.8; transform: scale(1); }
  30%  { opacity: 0.6; }
  50%  { opacity: 1; }
  100% { opacity: 0.4; }
}
.writing-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

/* 批改进度面板 */
.grade-progress-card {
  margin-top: var(--space-4);
  animation: slide-up 0.3s var(--easing-emphasized);
}

.grade-progress-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0;
}
.progress-track {
  flex: 1;
  height: 6px;
  background: var(--color-surface-secondary);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), #00bcd4);
  border-radius: 3px;
  transition: width 0.5s var(--easing-emphasized);
}
.progress-text {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  min-width: 36px;
  text-align: right;
}

.grade-think-chain {
  max-height: 240px;
  overflow-y: auto;
  padding: var(--space-2) 0;
  border-top: 1px solid var(--color-divider);
  border-bottom: 1px solid var(--color-divider);
}
.gtc-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: 3px 0;
  font-size: var(--text-xs);
  line-height: 1.5;
}
.gtc-icon {
  flex-shrink: 0;
  width: 18px;
  text-align: center;
}
.gtc-text {
  color: var(--color-text-secondary);
  word-break: break-all;
}
.gtc-thinking .gtc-text { color: var(--color-text-primary); }
.gtc-action .gtc-text { color: var(--color-primary); font-weight: var(--font-medium); }
.gtc-observation .gtc-text { color: var(--color-text-tertiary); font-size: 11px; }
.gtc-status .gtc-text { color: var(--color-text-secondary); font-style: italic; }

.grade-stream-output {
  padding: var(--space-3) 0;
  max-height: 300px;
  overflow-y: auto;
}
.grade-stream-output .stream-content {
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--color-text-primary);
}
.stream-cursor {
  display: inline;
  color: var(--color-primary);
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* 批改结果 */
.grade-result-card {
  animation: slide-up 0.4s var(--easing-emphasized);
}
@keyframes slide-up {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

.grade-feedback {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  margin: var(--space-4) var(--space-5);
  padding: var(--space-3) var(--space-4);
  background: var(--color-success-light);
  border-radius: var(--radius-md);
  border-left: 4px solid var(--color-success);
  color: var(--color-text-primary);
}

.grade-section {
  padding: 0 var(--space-5) var(--space-3);
}

.section-title {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  margin-bottom: var(--space-3);
  color: var(--color-text-primary);
}

/* 分步评分 */
.step-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
}
.step-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  min-width: 90px;
}
.step-bar {
  flex: 1;
  height: 8px;
  background: var(--color-bg);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.step-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.6s var(--easing-emphasized);
}
.fill-success { background: var(--color-success); }
.fill-warning { background: var(--color-warning); }
.step-score {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  min-width: 40px;
  text-align: right;
}
.step-status {
  font-size: var(--text-sm);
  font-weight: var(--font-bold);
  width: 20px;
  text-align: center;
}
.status-ok { color: var(--color-success); }
.status-err { color: var(--color-danger); }
.status-warn { color: var(--color-warning); }

/* 错误标注 */
.highlight-item {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
  padding: var(--space-3);
  background: var(--color-warning-light);
  border-radius: var(--radius-md);
  border-left: 3px solid var(--color-warning);
}
.hl-badge {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: var(--radius-sm);
  color: #fff;
  white-space: nowrap;
  height: fit-content;
  font-weight: var(--font-semibold);
}
.badge-error { background: var(--color-danger); }
.badge-polish { background: #722ED1; }
.hl-content { flex: 1; }
.hl-original { font-size: var(--text-sm); color: var(--color-text-tertiary); margin-bottom: 4px; text-decoration: line-through; }
.hl-fix { font-size: var(--text-sm); color: var(--color-success); font-weight: var(--font-medium); }
.hl-reason { margin-top: 4px; font-size: var(--text-xs); color: var(--color-text-tertiary); }

/* 改进建议 */
.suggestion-list {
  padding-left: 20px;
  color: var(--color-text-secondary);
}
.suggestion-list li {
  margin-bottom: var(--space-1);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}

.auto-save-alert {
  margin: var(--space-3) var(--space-5) var(--space-4);
}

/* 暗黑模式适配 */
html.dark .mode-tabs { background: var(--color-surface-secondary); }
html.dark .tb-answer { background: var(--color-surface); }
html.dark .grade-textarea :deep(.el-textarea__inner) { background: var(--color-surface-secondary) !important; border-color: var(--color-border) !important; }
html.dark .grade-textarea :deep(.el-textarea__inner:focus) { background: var(--color-surface) !important; }
html.dark .upload-btn { background: var(--color-surface-secondary); border-color: var(--color-border); }
html.dark .tool-chip { background: rgba(0, 180, 42, 0.12); }
html.dark .step-row { background: var(--color-surface-secondary); }
html.dark .highlight-item { background: rgba(255, 125, 0, 0.08); }
html.dark .grade-feedback { background: rgba(0, 180, 42, 0.08); }

/* ===== 图片预览区 ===== */
.image-preview-row {
  display: flex; gap: 8px; padding: 8px 12px 0;
  flex-wrap: wrap;
}
.image-preview-item {
  position: relative; width: 64px; height: 64px;
  border-radius: 8px; overflow: hidden;
  border: 1px solid var(--color-border);
}
.image-preview-item img {
  width: 100%; height: 100%; object-fit: cover;
}
.img-remove-btn {
  position: absolute; top: 0; right: 0;
  width: 20px; height: 20px;
  background: rgba(0,0,0,0.6); color: #fff; border: none;
  border-radius: 0 0 0 6px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
/* ===== 工具栏按钮 ===== */
.tool-btn, .voice-btn {
  width: 40px; height: 40px; border: none;
  border-radius: 50%; cursor: pointer;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: background 0.2s;
}
.tool-btn:hover, .voice-btn:hover {
  background: var(--color-bg-hover);
}
.voice-btn.recording {
  background: var(--color-danger, #f56c6c);
  color: #fff;
  animation: pulse 1s infinite;
}
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245,108,108,0.4); }
  50% { box-shadow: 0 0 0 8px rgba(245,108,108,0); }
}
</style>
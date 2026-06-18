# Chat 输入框 — 图片上传 + 语音输入 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在智能问答（chat 模式）输入框中增加图片上传（粘贴/拖拽/点击，微信式图文混排预览）和语音输入（按住录音，松开发送）。

**Architecture:** 前端在 AgentView.vue 的 chat 输入区域增加图片预览区和语音按钮。图片通过 base64 随 SSE payload 的 `images` 字段发送。语音通过 MediaRecorder 录音后 POST 到新端点 `/agent/voice-to-text` 调 DashScope 转文字。后端在 `agent_query_stream` 中接收 images，调用 OCR 后将文字拼入 user message content。

**Tech Stack:** Vue 3.5 + Element Plus 2.9 + MediaRecorder API + DashScope Paraformer 语音识别 + DashScope OCR

---

## 文件结构

| 文件 | 改动 | 职责 |
|------|------|------|
| `frontend/src/views/student/AgentView.vue` | 修改 | 输入框区域改造：图片预览区 + 语音按钮 + 图片选择/粘贴/拖拽 + 发送逻辑 |
| `frontend/src/api/index.js` | 修改 | 新增 `voiceToText()` API，`connectAgentSSE` 支持 images |
| `api/agent_routes.py` | 修改 | 新增 `POST /agent/voice-to-text`，`agent_query_stream` 接收 images |
| `api/shared_models.py` | 修改 | `QueryRequestModel` 新增 `images` 字段 |
| `langgraph_agent/chat_agent.py` | 修改 | `stream_agent_response` 接收 images，OCR 后拼入消息 |

---

### Task 1: 后端 — QueryRequestModel 新增 images 字段

**Files:**
- Modify: `api/shared_models.py`

- [ ] **Step 1: 添加 images 字段**

```python
# 在 QueryRequestModel 类的 query 字段后添加
class QueryRequestModel(BaseModel):
    query: str = Field(..., description="用户查询文本")
    images: Optional[List[str]] = Field(default=None, description="base64 图片列表（可选）")
    conversation_id: Optional[str] = Field(default=None, description="会话ID")
    user_id: Optional[str] = Field(default=None, description="用户ID")
    # ... 其余字段保持不变
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "from api.shared_models import QueryRequestModel; print(QueryRequestModel(query='test', images=['abc']).model_dump())"`
Expected: 输出包含 `images: ['abc']`

- [ ] **Step 3: Commit**

```bash
git add api/shared_models.py
git commit -m "feat: QueryRequestModel 新增 images 字段"
```

---

### Task 2: 后端 — chat_agent 支持图片处理

**Files:**
- Modify: `langgraph_agent/chat_agent.py` (stream_agent_response 函数, 第 202-210 行)

- [ ] **Step 1: 修改函数签名和消息构建**

将 `stream_agent_response` 的函数签名从：
```python
async def stream_agent_response(
    agent: CompiledStateGraph,
    user_message: str,
    config: RunnableConfig = None,
    history: List[dict] = None,
    conversation_id: str = None,
    user_id: str = None,
) -> AsyncGenerator[str, None]:
```
改为：
```python
async def stream_agent_response(
    agent: CompiledStateGraph,
    user_message: str,
    config: RunnableConfig = None,
    history: List[dict] = None,
    conversation_id: str = None,
    user_id: str = None,
    images: Optional[List[str]] = None,
) -> AsyncGenerator[str, None]:
```

在 `import json as _json` 之后、`# 创建 LangFuse 追踪` 之前，插入图片 OCR 处理：
```python
    # 图片 OCR 处理：将图片文字拼入用户消息
    if images:
        from llm.ocr_client import get_ocr_client
        ocr = get_ocr_client()
        ocr_texts = []
        for idx, img_b64 in enumerate(images):
            try:
                result = ocr.extract_text(img_b64, label=f"图片{idx+1}")
                text = result.get("extracted_text", "")
                if text:
                    ocr_texts.append(f"[图片{idx+1}的文字内容]\n{text}")
            except Exception as e:
                logger.warning(f"OCR 失败 (图片{idx+1}): {e}")
        if ocr_texts:
            user_message = user_message + "\n\n" + "\n\n".join(ocr_texts)
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "compile(open(r'd:\EduRAG智慧问答系统\langgraph_agent\chat_agent.py','r',encoding='utf-8').read(), 'chat_agent.py', 'exec'); print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: Commit**

```bash
git add langgraph_agent/chat_agent.py
git commit -m "feat: stream_agent_response 支持 images 参数，OCR 后拼入消息"
```

---

### Task 3: 后端 — agent_routes 新增 voice-to-text 端点 + 传递 images

**Files:**
- Modify: `api/agent_routes.py`

- [ ] **Step 1: 添加导入和 voice-to-text 端点**

在 `agent_routes.py` 文件末尾（`agent_router` 定义之后、`agent_query_stream` 之后）添加新端点。先在文件顶部增加导入：
```python
# 在现有 imports 下方添加
from fastapi import UploadFile, File, Form
```

然后在 `agent_router` 末尾（`agent_query_stream` 函数之后）添加：
```python
@agent_router.post("/agent/voice-to-text")
async def voice_to_text(audio: UploadFile = File(...)):
    """
    语音转文字：接收音频文件，调用 DashScope Paraformer 识别，返回文字。
    """
    import base64
    import os

    audio_bytes = await audio.read()
    if len(audio_bytes) < 500:
        raise HTTPException(status_code=400, detail="录音太短，请重试")

    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("LLM_API_KEY") or ""
    if not api_key:
        from core.config_manager import ConfigManager
        api_key = ConfigManager().dashscope_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="语音识别服务未配置")

    try:
        import dashscope
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

        class _Callback(RecognitionCallback):
            def __init__(self):
                self.text = ""
            def on_open(self):
                logger.debug("[VoiceToText] 连接已建立")
            def on_event(self, result: RecognitionResult):
                sentence = result.get_sentence()
                if sentence and sentence.get("text"):
                    self.text = sentence["text"]
            def on_close(self):
                pass
            def on_error(self, msg):
                logger.error(f"[VoiceToText] 错误: {msg}")

        callback = _Callback()
        recognition = Recognition(
            model="paraformer-realtime-v2",
            format="wav",
            sample_rate=16000,
            callback=callback,
        )
        # 将音频数据编码为 base64 后调用
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        recognition.call(audio_b64)
        text = callback.text.strip()

        if not text:
            raise HTTPException(status_code=422, detail="未识别到语音内容")

        logger.info(f"[VoiceToText] 识别成功: {text[:60]}...")
        return {"text": text}
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=500, detail="dashscope 未安装")
    except Exception as e:
        logger.error(f"[VoiceToText] 异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"语音识别失败: {str(e)}")
```

- [ ] **Step 2: 修改 agent_query_stream 传递 images**

在 `agent_query_stream` 函数中，`stream_agent_response` 调用处（第 131-133 行）增加 `images` 参数：
```python
# 第 131-133 行，改为：
            async for sse_str in stream_agent_response(
                agent, request.query, config=config, history=history,
                conversation_id=conversation_id, user_id=request.user_id,
                images=request.images,
            ):
```

同样修改 `agent_query`（非流式）中的 `agent_messages.append(HumanMessage(content=request.query))` 之前，加入 OCR 处理（第 47 行前）：
```python
    # 在 agent_messages.append(HumanMessage(content=request.query)) 之前插入
    query_text = request.query
    if request.images:
        from llm.ocr_client import get_ocr_client
        ocr = get_ocr_client()
        for idx, img_b64 in enumerate(request.images):
            try:
                result = ocr.extract_text(img_b64, label=f"图片{idx+1}")
                text = result.get("extracted_text", "")
                if text:
                    query_text += f"\n\n[图片{idx+1}的文字内容]\n{text}"
            except Exception as e:
                logger.warning(f"OCR 失败: {e}")
    agent_messages.append(HumanMessage(content=query_text))
```

- [ ] **Step 3: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "compile(open(r'd:\EduRAG智慧问答系统\api\agent_routes.py','r',encoding='utf-8').read(), 'agent_routes.py', 'exec'); print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 4: Commit**

```bash
git add api/agent_routes.py
git commit -m "feat: 新增 voice-to-text 端点，agent_query/stream 传递 images"
```

---

### Task 4: 前端 — 新增 voiceToText API

**Files:**
- Modify: `frontend/src/api/index.js`

- [ ] **Step 1: 添加 voiceToText 函数**

在 `index.js` 中 `connectAgentSSE` 函数之后（第 107 行后）添加：
```javascript
/**
 * 语音转文字：上传音频文件，返回识别文字
 * @param {Blob} audioBlob - 录音 blob
 * @returns {Promise<{text: string}>}
 */
export function voiceToText(audioBlob) {
  const form = new FormData()
  form.append('audio', audioBlob, 'recording.wav')
  return request.post('/agent/voice-to-text', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  })
}
```

- [ ] **Step 2: 修改 connectAgentSSE 的注释**

将第 91 行的注释从：
```javascript
 * @param {object} data - { query: string, top_k?: number }
```
改为：
```javascript
 * @param {object} data - { query: string, conversation_id?: string, images?: string[] }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/index.js
git commit -m "feat: 新增 voiceToText API，connectAgentSSE 支持 images"
```

---

### Task 5: 前端 — AgentView.vue 输入框改造（图片预览区 + 样式）

**Files:**
- Modify: `frontend/src/views/student/AgentView.vue`

- [ ] **Step 1: 替换 chat 模式输入区域模板**

将第 100-117 行的输入区域替换为：
```html
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
```

- [ ] **Step 2: 新增样式（加到 `<style scoped>` 末尾）**

```css
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
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/student/AgentView.vue
git commit -m "feat: AgentView 输入框模板和样式改造（图片预览区+语音按钮）"
```

---

### Task 6: 前端 — AgentView.vue 脚本逻辑（图片上传 + 语音 + 发送）

**Files:**
- Modify: `frontend/src/views/student/AgentView.vue` (script 部分)

- [ ] **Step 1: 新增状态和导入**

在 `import { connectAgentSSE } from '@/api/index'` 行（第 87 行附近）改为：
```javascript
import { connectAgentSSE, voiceToText } from '@/api/index'
```

在 script setup 中，现有状态变量（第 374-380 行之后）添加：
```javascript
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
```

- [ ] **Step 2: 修改 handleSend 发送 images**

将 `handleSend` 函数（第 417 行）中的发送校验从：
```javascript
  if (!text || thinking.value) return
```
改为：
```javascript
  const hasImages = imagePreviews.value.length > 0
  if (!text && !hasImages || thinking.value) return
```

将 SSE payload（第 444-445 行）从：
```javascript
  const stream = connectAgentSSE(
    { query: text, conversation_id: conversationId.value },
```
改为：
```javascript
  const stream = connectAgentSSE(
    { query: text, conversation_id: conversationId.value, images: imagePreviews.value.map(i => i.base64) },
```

在发送成功后清空图片预览（在 `input.value = ''` 之后添加）：
```javascript
  imagePreviews.value = []
```

- [ ] **Step 3: 导入 ElMessage**

在 `import { ElMessage } from 'element-plus'` 已存在则跳过，否则在 script 顶部添加：
```javascript
import { ElMessage } from 'element-plus'
```

- [ ] **Step 4: 导入新增图标**

在 `import { Picture, Microphone, Close } from '@element-plus/icons-vue'` 已存在则跳过，否则确保图标可用。Element Plus 图标已全局注册，无需额外导入。

- [ ] **Step 5: 语法检查**

Run: `cd d:\EduRAG智慧问答系统\frontend && npx vue-tsc --noEmit --project tsconfig.json 2>&1 | head -20`
Expected: 无新增错误（或仅类型提示）

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/student/AgentView.vue
git commit -m "feat: AgentView 图片上传/粘贴/拖拽 + 语音录音转文字发送"
```

---

### Task 7: 验证

- [ ] **Step 1: 重启服务**

```bash
# 终端1: 重启后端
cd d:\EduRAG智慧问答系统
& .venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 终端2: 重启前端
cd d:\EduRAG智慧问答系统\frontend
npx vite
```

- [ ] **Step 2: 手动测试图片上传**

1. 打开智能问答页面，切换到 chat 模式
2. 点击图片按钮，选择一张图片 → 应显示缩略图预览
3. Ctrl+V 粘贴剪贴板图片 → 应显示缩略图
4. 输入文字 + 图片 → 点击发送 → 应正常发送，图片 base64 随 SSE 发送
5. 点击缩略图的 × 按钮 → 应删除该图片

- [ ] **Step 3: 手动测试语音输入**

1. 长按语音按钮 → 按钮变红，显示录音动画
2. 说一句话 → 松开 → 应自动识别文字并发送
3. 录音 < 1 秒 → 应提示"录音太短"

- [ ] **Step 4: 验证后端日志**

```bash
# 观察后端日志，确认 OCR 调用和语音识别调用正常
tail -f edurag.log | grep -E "OCR|VoiceToText"
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: chat 输入框图片上传+语音输入完成，验证通过"
```
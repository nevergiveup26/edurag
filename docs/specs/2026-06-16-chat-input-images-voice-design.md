# Chat 模式输入框 — 图片上传 + 语音输入

**日期**: 2026-06-16
**范围**: `frontend/src/views/student/AgentView.vue` + `api/agent_routes.py`

---

## 目标

在智能问答（chat 模式）输入框中增加：
- 图片上传（粘贴/拖拽/点击，微信式图文混排预览）
- 语音输入（按住录音，松开后自动转文字并发送）

---

## 设计

### 前端改造

```
改造前:  [el-input 文本输入框] [发送按钮]

改造后:
┌─────────────────────────────────────────────────────────────┐
│  [图片缩略图1] [图片缩略图2] [图片缩略图3] ...   [×删除]      │  ← 图片预览区
│  ┌───────────────────────────────────────────────────────┐  │
│  │  文字输入区域...                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│  [🖼图片]                                 [🎤语音] [发送 →]  │  ← 底部工具栏
└─────────────────────────────────────────────────────────────┘
```

**图片上传**：点击图片按钮 → 打开文件选择器（`accept="image/*"`）→ 选中后转为 base64，以缩略图形式展示在输入框上方，可删除。支持粘贴（Ctrl+V 粘贴剪贴板图片）和拖拽到输入区域。

**语音输入**：长按语音按钮 → 调用 `navigator.mediaDevices.getUserMedia` 录音 → 松开后停止录音 → 将音频 blob 发送到后端 `/api/v1/agent/voice-to-text` → 后端调用 DashScope 语音识别 → 返回文字 → 前端自动填入输入框并发送。

**发送变更**：`connectAgentSSE` 的 payload 从 `{ query, conversation_id }` 扩展为 `{ query, conversation_id, images: [base64...] }`。

### 后端改造

| 改动点 | 说明 |
|--------|------|
| `QueryRequestModel` 新增 `images` 字段 | `List[str]`，可选，base64 图片列表 |
| `POST /agent/query` 和 `POST /agent/query/stream` | 传递 images 到 agent |
| 新增 `POST /agent/voice-to-text` | 接收音频 blob，调用 DashScope Paraformer 语音识别，返回文字 |
| 图片处理 | 已有 `OCRClient.extract_text()` 可直接复用，图片 OCR 结果拼入 system prompt 的 context |

### 数据流

```
用户粘贴/选择图片
  → FileReader.readAsDataURL() → base64 预览
  → 发送时: images 字段加入 SSE payload

用户按住语音按钮
  → MediaRecorder 录音 → 松开 → Blob
  → POST /agent/voice-to-text (multipart/form-data)
  → DashScope Paraformer 语音识别 → 返回文字
  → 前端自动填入输入框 → 触发发送
```

### 边界情况

- 图片 > 10MB 时前端提示过大，拒绝上传
- 录音 < 1 秒时忽略（防误触）
- 语音识别失败时提示用户"语音识别失败，请手动输入"
- 图片 OCR 失败时仍正常发送，图片作为视觉上下文传给 LLM（qwen-max 支持图片输入）
- 发送中（thinking）时禁用图片上传和语音按钮

---

## 涉及文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `frontend/src/views/student/AgentView.vue` | 修改 | 输入框改造为主要改动 |
| `api/agent_routes.py` | 修改 | 新增 voice-to-text 端点，images 字段传递 |
| `api/shared_models.py` | 修改 | QueryRequestModel 新增 images 字段 |
| `langgraph_agent/chat_agent.py` | 修改 | 接收 images 参数，调用 OCR 拼入 context |
| `langgraph_agent/model.py` | 修改 | create_chat_model 支持图片消息 |
# Phase 2 前端拆分规格书

> **状态：📋 待执行**
> **依赖：Phase 1 后端改造已完成**（JWT 鉴权 / 学生端路由 / 管理端路由均已就绪）
>
> 项目根目录：`d:\EduRAG智慧问答系统`
> Python 解释器：`G:\anaconda3\python.exe`

---

## 一、目标

将当前单页面 Gradio UI（`ui/gradio_app.py`，1386 行，10 个标签页）拆分为两个独立前端应用：

| 应用 | 端口 | 用户角色 |
|------|------|----------|
| **学生端** (`ui/student_app.py`) | 7860 | 学生（需登录，JWT student） |
| **管理端** (`ui/admin_app.py`) | 7861 | 管理员（需登录，JWT admin） |

拆分后的 `ui/gradio_app.py` 保留不动（作为旧版单页面备查）。

---

## 二、前置条件（已就绪）

| 条件 | 状态 |
|------|:--:|
| 后端 API 端点拆分（公共 / student / admin） | ✅ Phase 1 完成 |
| JWT 鉴权模块 `api/auth.py` | ✅ |
| 预设账号（admin + 2024001） | ✅ `scripts/init_admin.py` |
| `run.py` 启动入口已预留 `ui-student` / `ui-admin` / `all-new` 模式 | ✅ 已就绪 |
| 所有标签页的 Python 函数可复用 | ✅ `gradio_app.py` 中现成 |

---

## 三、当前 Gradio 标签页与归属分配

| 标签页 | 行号 | 核心函数 | 目标归属 |
|--------|------|----------|:--:|
| 💬 问答 | 935-1013 | `chat_with_system_stream` | **学生端** |
| 📊 检索可视化 | 1059-1082 | `visualize_retrieval` | **学生端** |
| 🔖 引用高亮 | 1199-1226 | `query_with_citations` | **学生端** |
| 📄 上传文档 | 1016-1040 | `upload_file` | **管理端** |
| 📚 FAQ管理 | 1043-1056 | `import_faq_data` | **管理端** |
| 📈 模型评估 | 1085-1109 | `run_evaluation_tab` | **管理端** |
| 🎯 RAGAS评估 | 1112-1136 | `run_ragas_evaluation_tab` | **管理端** |
| 📁 知识库管理 | 1139-1196 | `create/list/add/delete_kb` | **管理端** |
| 🔍 追踪 | 1229-1264 | `view_langfuse_traces` | **管理端** |
| 🤖 Agent | 1267-1300 | `run_agent_query` | **管理端** |
| 🖼️ 多模态 | 1303-1346 | `upload_multimodal_file` 等 | **管理端** |
| ℹ️ 关于 | 1349-1375 | — | **两个端都保留** |

---

## 四、通用模块：Token 管理

**新建文件**：`ui/auth_utils.py`

两个应用都需要的能力，抽取到公共模块：

```python
"""
Token 管理工具 — 学生端 & 管理端共享
"""
import requests

API_BASE = "http://127.0.0.1:8000/api/v1"


def login(role: str, username: str, password: str) -> dict:
    """
    统一登录，返回 {"success": True, "token": "eyJ...", "user": {...}}
    或 {"success": False, "error": "..."}
    """
    url = f"{API_BASE}/{role}/login"
    try:
        r = requests.post(url, json={"username": username, "password": password}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {"success": True, "token": data["token"], "user": data["user"]}
        return {"success": False, "error": r.json().get("detail", "登录失败")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_student(username: str, password: str, display_name: str = "") -> dict:
    """学生注册"""
    try:
        r = requests.post(f"{API_BASE}/student/register",
                         json={"username": username, "password": password, "display_name": display_name},
                         timeout=10)
        if r.status_code == 200:
            return {"success": True, "message": r.json().get("message", "注册成功")}
        return {"success": False, "error": r.json().get("detail", "注册失败")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def auth_headers(token: str) -> dict:
    """生成带 Authorization 的请求头"""
    return {"Authorization": f"Bearer {token}"}
```

> **说明**：`API_BASE` 去掉了 `/api/v1` 后缀，因为登录接口路径是 `/api/v1/student/login`，而各标签页函数调用的 `API_BASE` 保留 `/api/v1` 后缀直接拼路径。两者分开定义。

---

## 五、学生端新建文件

**新建文件**：`ui/student_app.py`

### 5.1 文件职责

| 能力 | 来源 |
|------|------|
| 登录 | **新建** — username/password 输入 → JWT token 存入 `gr.State` |
| 注册 | **新建** — 学号注册入口 |
| 💬 问答 | **复用** — `chat_with_system_stream` 完整迁移 |
| 📊 检索可视化 | **复用** — `visualize_retrieval` 完整迁移 |
| 🔖 引用高亮 | **复用** — `query_with_citations` 完整迁移 |
| 📜 对话历史 | **新建** — 调用 `GET /student/conversations` + `GET /student/conversation/{id}` |
| 👍👎 反馈 | **新建** — 调用 `POST /student/feedback` |
| ℹ️ 关于 | **复用** — 精简版 |

### 5.2 UI 布局设计

```
┌──────────────────────────────────────────────┐
│  🔐 登录面板（未登录时显示）                     │
│  ┌──────────────┐ ┌──────────────┐ ┌────────┐ │
│  │ 学号          │ │ 密码          │ │ 登录   │ │
│  └──────────────┘ └──────────────┘ └────────┘ │
│  [ 注册新账号 ]  → 展开注册表单               │
│  ┌──────────────────────────────────────────┐ │
│  │ 学号 │ 密码 │ 姓名 │ 注册 │              │ │
│  └──────────────────────────────────────────┘ │
│  [登录状态: 已登录 | 学号: 2024001] [退出]     │
├──────────────────────────────────────────────┤
│  ┌─ 标签页 ─────────────────────────────────┐ │
│  │ 💬 问答 │ 🔖 引用 │ 📊 可视化 │ 📜 历史 │ ℹ️ │ │
│  └──────────────────────────────────────────┘ │
│  (标签页切换，未登录时灰掉)                     │
└──────────────────────────────────────────────┘
```

### 5.3 标签页详细说明

#### Tab 1: 💬 问答（从 gradio_app.py 迁移）

```
复用的代码块：
- chat_with_system_stream() 函数（第43-214行）
- check_system_status() 函数（第252-268行）
- thinking_icons 常量
- 策略选择 radio、top_k slider、show_sources checkbox、with_citations checkbox
- 策略说明 accordion

token 注入：
- chat_with_system_stream 接收 token 参数（从 gr.State 读取）
- 请求头加 Authorization: Bearer <token>
```

#### Tab 2: 🔖 引用高亮（从 gradio_app.py 迁移）

```
复用的代码块：
- query_with_citations() 函数（第671-711行）
- 检索策略 radio、top_k slider

token 注入：同上
```

#### Tab 3: 📊 检索可视化（从 gradio_app.py 迁移）

```
复用的代码块：
- visualize_retrieval() 函数（第271-366行）

token 注入：同上
```

#### Tab 4: 📜 对话历史（新建）

```python
def get_conversation_history(token: str) -> str:
    """获取对话历史"""
    try:
        r = requests.get(f"{API_BASE}/student/conversations",
                        headers=auth_headers(token), timeout=10)
        r.raise_for_status()
        data = r.json()
        conversations = data.get("conversations", [])
        
        if not conversations:
            return "<p style='color:#999;'>暂无对话记录。</p>"
        
        html = "<div style='font-family:sans-serif;'>"
        for conv in conversations:
            html += f"""
            <div style='padding:8px;margin:4px 0;background:#fafafa;border-radius:6px;
                border-left:3px solid #2196F3;'>
                <b>{conv.get('title', '新对话')}</b>
                <span style='font-size:11px;color:#999;'> | {conv.get('created_at', '')[:19]}</span>
                <div style='font-size:10px;color:#bbb;'>ID: {conv.get('id', '')[:12]}...</div>
            </div>"""
        html += "</div>"
        return html
    except Exception as e:
        return f"<p style='color:red;'>获取失败: {str(e)}</p>"
```

#### Tab 5: ℹ️ 关于

精简版"关于"信息，突出学生视角。

### 5.4 登录状态管理（核心）

```python
def create_student_app():
    """创建学生端 Gradio 应用"""
    
    with gr.Blocks(title="EduRAG - 学生端") as app:
        # ===== 状态变量（Gradio 运行时保持）=====
        token_state = gr.State("")           # JWT token
        user_state = gr.State({})            # {"id": ..., "username": ..., "role": ...}
        
        gr.Markdown("# 🎓 EduRAG 智慧问答 — 学生端")
        
        # ===== 登录面板 =====
        with gr.Column(visible=True) as login_panel:
            gr.Markdown("### 学生登录")
            with gr.Row():
                username_input = gr.Textbox(label="学号", placeholder="输入学号")
                password_input = gr.Textbox(label="密码", type="password", placeholder="输入密码")
                login_btn = gr.Button("登录", variant="primary")
            login_status = gr.Markdown("")
            
            # 注册入口
            with gr.Accordion("📝 注册新账号", open=False):
                reg_username = gr.Textbox(label="学号")
                reg_password = gr.Textbox(label="密码", type="password")
                reg_display = gr.Textbox(label="姓名（可选）")
                reg_btn = gr.Button("注册")
                reg_output = gr.Markdown("")
        
        # ===== 已登录面板 =====
        with gr.Column(visible=False) as main_panel:
            with gr.Row():
                gr.Markdown("")  # spacer
                logout_btn = gr.Button("🚪 退出登录", variant="stop", scale=1)
            
            with gr.Tabs() as tabs:
                with gr.TabItem("💬 问答"):
                    # ... 同 gradio_app.py 问答标签页 ...
                    pass
                
                with gr.TabItem("🔖 引用高亮"):
                    # ... 同 gradio_app.py 引用高亮标签页 ...
                    pass
                
                with gr.TabItem("📊 检索可视化"):
                    # ... 同 gradio_app.py 检索可视化标签页 ...
                    pass
                
                with gr.TabItem("📜 对话历史"):
                    history_refresh = gr.Button("刷新")
                    history_output = gr.HTML()
                
                with gr.TabItem("ℹ️ 关于"):
                    gr.Markdown("...")
        
        # ===== 事件绑定 =====
        
        def do_login(username, password):
            result = login("student", username, password)
            if result["success"]:
                return (
                    result["token"],                    # → token_state
                    result["user"],                     # → user_state
                    gr.update(visible=False),           # → login_panel
                    gr.update(visible=True),            # → main_panel
                    f"✅ 登录成功，欢迎 {result['user']['username']}"
                )
            return "", {}, gr.update(visible=True), gr.update(visible=False), f"❌ {result['error']}"
        
        def do_logout():
            return "", {}, gr.update(visible=True), gr.update(visible=False), ""
        
        def do_register(username, password, display_name):
            result = register_student(username, password, display_name)
            return f"✅ {result['message']}" if result["success"] else f"❌ {result['error']}"
        
        login_btn.click(
            do_login,
            inputs=[username_input, password_input],
            outputs=[token_state, user_state, login_panel, main_panel, login_status]
        )
        logout_btn.click(
            do_logout,
            inputs=[],
            outputs=[token_state, user_state, login_panel, main_panel, login_status]
        )
        reg_btn.click(
            do_register,
            inputs=[reg_username, reg_password, reg_display],
            outputs=reg_output
        )
    
    return app
```

---

## 六、管理端新建文件

**新建文件**：`ui/admin_app.py`

### 6.1 文件职责

| 能力 | 来源 |
|------|------|
| 登录 | **新建** — username/password 输入 → JWT token |
| 📄 上传文档 | **复用** — `upload_file` 完整迁移 |
| 📚 FAQ管理 | **复用** — `import_faq_data` 完整迁移 |
| 📈 模型评估 | **复用** — `run_evaluation_tab` 完整迁移 |
| 🎯 RAGAS评估 | **复用** — `run_ragas_evaluation_tab` 完整迁移 |
| 📁 知识库管理 | **复用** — 4 个 kb 函数完整迁移 |
| 🔍 追踪 | **复用** — `view_langfuse_traces` 完整迁移 |
| 🤖 Agent | **复用** — `run_agent_query` + `view_agent_tools` |
| 🖼️ 多模态 | **复用** — `upload_multimodal_file` + `query_multimodal` + `view_multimodal_models` |
| 📊 仪表盘 | **新建** — 调用 `GET /admin/stats` |
| ℹ️ 关于 | **复用** — 精简版 |

### 6.2 UI 布局设计

```
┌──────────────────────────────────────────────┐
│  🔐 管理端登录                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌────────┐ │
│  │ 管理员账号     │ │ 密码          │ │ 登录   │ │
│  └──────────────┘ └──────────────┘ └────────┘ │
│  [登录状态: 已登录 | 用户名: admin] [退出]      │
├──────────────────────────────────────────────┤
│  ┌── 标签页 ────────────────────────────────┐  │
│  │📊仪表盘│📄上传│📚FAQ│📈评估│🎯RAGAS│📁知识库│…│  │
│  └──────────────────────────────────────────┘  │
│  │🔍追踪│🤖Agent│🖼️多模态│ℹ️关于│               │
│  (未登录时灰掉)                                 │
└──────────────────────────────────────────────┘
```

### 6.3 仪表盘 Tab（新建）

```python
def admin_dashboard(token: str) -> str:
    """管理员仪表盘"""
    try:
        r = requests.get(f"{API_BASE}/admin/stats",
                        headers=auth_headers(token), timeout=10)
        r.raise_for_status()
        data = r.json()
        
        fb = data.get("feedback", {})
        
        html = f"""
        <div style='font-family:sans-serif;'>
            <div style='display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px;'>
                <div style='flex:1;min-width:120px;background:#e3f2fd;border-radius:8px;padding:16px;text-align:center;'>
                    <div style='font-size:12px;color:#666;'>文档总数</div>
                    <div style='font-size:28px;font-weight:bold;color:#1976D2;'>{data.get('total_documents', 0)}</div>
                </div>
                <div style='flex:1;min-width:120px;background:#e8f5e9;border-radius:8px;padding:16px;text-align:center;'>
                    <div style='font-size:12px;color:#666;'>知识库</div>
                    <div style='font-size:28px;font-weight:bold;color:#388E3C;'>{data.get('total_knowledge_bases', 0)}</div>
                </div>
                <div style='flex:1;min-width:120px;background:#fff3e0;border-radius:8px;padding:16px;text-align:center;'>
                    <div style='font-size:12px;color:#666;'>用户数</div>
                    <div style='font-size:28px;font-weight:bold;color:#F57C00;'>{data.get('total_users', 0)}</div>
                </div>
                <div style='flex:1;min-width:120px;background:#fce4ec;border-radius:8px;padding:16px;text-align:center;'>
                    <div style='font-size:12px;color:#666;'>反馈好评率</div>
                    <div style='font-size:28px;font-weight:bold;color:#E91E63;'>{fb.get('like_rate', 0)*100:.0f}%</div>
                </div>
            </div>
            
            <h3>📊 反馈统计</h3>
            <div style='display:flex;gap:12px;'>
                <div style='flex:1;background:#e8f5e9;border-radius:8px;padding:12px;text-align:center;'>
                    <b>👍 好评</b><br/>{fb.get('likes', 0)}
                </div>
                <div style='flex:1;background:#ffebee;border-radius:8px;padding:12px;text-align:center;'>
                    <b>👎 差评</b><br/>{fb.get('dislikes', 0)}
                </div>
                <div style='flex:1;background:#f5f5f5;border-radius:8px;padding:12px;text-align:center;'>
                    <b>总计</b><br/>{fb.get('total', 0)}
                </div>
            </div>
        </div>"""
        return html
    except Exception as e:
        return f"<p style='color:red;'>获取仪表盘失败: {str(e)}</p>"
```

---

## 七、标签页函数 Token 注入模式

所有从 `gradio_app.py` 复用的函数需要统一改造：**接收 token 参数并通过 headers 注入**。

### 改造前（无需鉴权）

```python
def upload_file(file) -> str:
    resp = requests.post(f"{API_BASE}/upload", files=files, timeout=120)
```

### 改造后（注入 token）

```python
def upload_file(token: str, file) -> str:
    resp = requests.post(
        f"{API_BASE}/upload",
        files=files,
        headers=auth_headers(token),
        timeout=120
    )
```

涉及的函数清单：

| 函数 | 原 API 路径 | 目标 API 路径 | token 注入 |
|------|------------|-------------|:--:|
| `chat_with_system_stream` | `/query/stream` | 不变（公共） | 可选 |
| `visualize_retrieval` | `/query` | 不变（公共） | 可选 |
| `query_with_citations` | `/student/query/citations` | 不变 | ✅ |
| `check_system_status` | `/stats` | 不变（公共） | 否 |
| `upload_file` | `/upload` | 不变（公共） | 可选 |
| `import_faq_data` | `/admin/faq/import` | 不变 | ✅ |
| `run_evaluation_tab` | `/admin/evaluate` | 不变 | ✅ |
| `run_ragas_evaluation_tab` | `/admin/evaluate/ragas` | 不变 | ✅ |
| `create_knowledge_base` | `/kb` → `/admin/kb` | 不变 | ✅ |
| `list_knowledge_bases` | `/kb` → `/admin/kb` | 不变 | ✅ |
| `add_docs_to_kb` | `/admin/kb/{id}/documents` | 不变 | ✅ |
| `delete_kb` | `/admin/kb/{id}` | 不变 | ✅ |
| `view_langfuse_traces` | `/admin/traces` | 不变 | ✅ |
| `run_agent_query` | `/admin/agent/query` | 不变 | ✅ |
| `view_agent_tools` | `/admin/agent/tools` | 不变 | ✅ |
| `upload_multimodal_file` | `/admin/multimodal/upload` | 不变 | ✅ |
| `query_multimodal` | `/admin/multimodal/query` | 不变 | ✅ |
| `view_multimodal_models` | `/admin/multimodal/models` | 不变 | ✅ |

---

## 八、任务分解

### 任务 1：创建公共模块 `ui/auth_utils.py`

- **内容**：`login()`、`register_student()`、`auth_headers()` 函数
- **依赖**：无
- **预计行数**：~30 行

### 任务 2：创建学生端 `ui/student_app.py`

- **内容**：登录/注册面板 + 状态管理 + 5 个标签页（问答/引用/可视化/历史/关于）
- **依赖**：任务 1
- **新增代码**：登录面板 (~60行)、对话历史 (~30行)
- **迁移代码**：从 `gradio_app.py` 迁移 3 个标签页函数 (~380行)
- **预计行数**：~550 行

### 任务 3：创建管理端 `ui/admin_app.py`

- **内容**：登录面板 + 状态管理 + 9 个标签页（仪表盘/上传/FAQ/评估/RAGAS/知识库/追踪/Agent/多模态/关于）
- **依赖**：任务 1
- **新增代码**：登录面板 (~40行)、仪表盘 (~50行)
- **迁移代码**：从 `gradio_app.py` 迁移 8 个标签页函数 (~820行)
- **预计行数**：~950 行

### 任务 4：验证 run.py 启动模式

- **内容**：确认 `--mode ui-student` / `--mode ui-admin` / `--mode all-new` 正确导入
- **依赖**：任务 2、3
- **内容**：`run.py` 已有入口代码（第49-76行、第104-107行、第118-123行），只需确认导入路径正确

### 任务 5：端到端测试

- **内容**：
  1. API 服务启动
  2. 管理端登录 → 各标签页功能验证
  3. 学生端登录 → 各标签页功能验证
  4. 鉴权拦截测试（未登录时功能不可用）

---

## 九、执行步骤

```
步骤 1: 新建 ui/auth_utils.py 公共模块
步骤 2: 新建 ui/student_app.py   （复制函数 + 加 token 参数 + 加登录面板）
步骤 3: 新建 ui/admin_app.py     （复制函数 + 加 token 参数 + 加登录面板 + 仪表盘）
步骤 4: 验证 run.py 各模式可用
步骤 5: 启动 all-new 模式全链路测试
```

---

## 十、重要约束

1. **不要删除 `ui/gradio_app.py`**。保留作为旧版单页面备查。
2. **公共函数复制到新文件时同步修改函数签名**。所有函数增加 `token: str` 作为第一个参数（即便公共接口不需要鉴权也可以传 `""` 保持签名一致）。
3. **API_BASE 统一复用现有定义**。`http://127.0.0.1:8000/api/v1`，在 `auth_utils.py` 和两个 app 文件中各自定义（不跨文件 import 避免循环依赖）。
4. **Gradio State 机制**。token 通过 `gr.State("")` 在组件间传递，不写入文件或环境变量。
5. **函数签名变化后 Gradio event binding 同步更新**。所有 `fn=` 参数对应的 `inputs=` 第一位加 `token_state`。
6. **端口不冲突**。学生端 7860、管理端 7861、API 8000。
7. **中文注释完整保留**。迁移的代码块不裁剪注释。
8. **IntelliSense 依赖无新增**。不需要安装新 pip 包。

---

## 十一、启动命令一览

```bash
# 仅 API
G:\anaconda3\python.exe run.py --mode api

# 旧版单页面 UI（保留兼容）
G:\anaconda3\python.exe run.py --mode ui

# API + 旧版 UI（保留兼容）
G:\anaconda3\python.exe run.py --mode all

# ===== Phase 2 新增模式 =====

# 仅学生端（需先启动 API）
G:\anaconda3\python.exe run.py --mode ui-student

# 仅管理端（需先启动 API）
G:\anaconda3\python.exe run.py --mode ui-admin

# 一键启动全部（API + 学生端 + 管理端）
G:\anaconda3\python.exe run.py --mode all-new
```

---

## 十二、验收标准

| 验收项 | 标准 |
|--------|------|
| 学生端登录 | 用 `2024001 / 123456` 登录成功，进入问答界面 |
| 学生端鉴权 | 未登录时所有功能不可用 / 报错提示登录 |
| 学生端问答 | 输入问题后正常流式返回答案 |
| 学生端引用 | 引用高亮标签页正常工作 |
| 学生端历史 | 对话历史标签页显示历史记录 |
| 管理端登录 | 用 `admin / admin123` 登录成功，进入仪表盘 |
| 管理端鉴权 | 学生 token 无法访问管理端功能 |
| 管理端仪表盘 | 显示文档数/知识库数/用户数/反馈统计 |
| 管理端评估 | 模型评估和 RAGAS 评估正常运行 |
| 管理端知识库 | CRUD 操作正常 |
| 管理端 Agent | Agent 查询正常执行 |
| 管理端多模态 | 文档上传和查询正常 |
| 一键启动 | `--mode all-new` 同时启动 API + 两个 UI |
| 旧版兼容 | `--mode ui` 和 `--mode all` 仍然可用 |
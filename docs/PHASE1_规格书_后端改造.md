# Phase 1 后端改造规格书 — 已完成

> **状态：✅ 全部 7 个任务已完成（2026-06-08 执行）**
> 本文档记录实际执行结果，供后续 Phase 2 参考。
> 项目根目录：`d:\EduRAG智慧问答系统`
> Python 解释器：`G:\anaconda3\python.exe`

---

## 一、改造目标（已完成）

1. ✅ **拆分路由**：分为 `/api/v1/student/`（学生端）和 `/api/v1/admin/`（管理端），公共端点保留在 `routes.py`
2. ✅ **新增用户体系**：`users` 表 + JWT 鉴权，学生用学号登录，管理员用账号密码登录
3. ✅ **新增知识库 CRUD**：补全 `knowledge_bases` + `kb_documents` 的方法
4. ✅ **新增反馈功能**：学生可对答案点 👍👎，存入 `feedback` 表
5. ✅ **保持现有功能不受影响**：所有原有接口继续可用，Gradio 适配完成

---

## 二、当前代码结构

> 标注 ⭐ 的是本次改造新增或修改的文件

```
d:\EduRAG智慧问答系统\
├── api/                        # ⭐ 路由层改造
│   ├── __init__.py
│   ├── main.py                 # ⭐ 注册 3 个路由器
│   ├── routes.py               # ⭐ 精简为 6 个公共端点（1202 → ~350 行）
│   ├── student_routes.py       # ⭐ 新建：学生端 10 个端点
│   ├── admin_routes.py         # ⭐ 新建：管理端 25 个端点
│   └── auth.py                 # ⭐ 新建：JWT 鉴权模块
├── scripts/                    # ⭐ 新建
│   └── init_admin.py           # ⭐ 管理员/学生账号初始化脚本
├── agent/
│   ├── rag_agent.py            # ReAct Agent
│   └── tools.py                # 工具注册表（search/calculator/web_search）
├── citation/
│   └── citation_parser.py      # 内联引用解析+HTML渲染
├── kb/
│   └── knowledge_base.py       # 知识库CRUD + 高级搜索
├── monitoring/
│   └── langfuse_tracer.py      # 全链路追踪（兼容Langfuse协议）
├── core/
│   ├── config_manager.py       # 配置管理器（单例，读 config.ini）
│   ├── models.py               # 数据模型
│   ├── query_pipeline.py       # 查询编排
│   └── logger.py               # 日志
├── database/
│   ├── mysql_db.py             # ⭐ MySQL：新增 users/feedback 表 + 3 组 CRUD 方法
│   ├── milvus_db.py            # Milvus 向量库
│   ├── redis_cache.py          # Redis 缓存
│   └── chunk_store.py          # 文档片段持久化
├── config/
│   └── config.ini              # 配置文件
├── data_processor/
│   ├── document_loader.py      # 文档加载
│   ├── document_splitter.py    # 文档切分
│   ├── vectorizer.py           # 文本向量化（BGE/m3e等6种模型）
│   ├── multimodal_loader.py    # PDF/DOCX/PPTX图片表格提取
│   └── vision_encoder.py       # 多模态视觉编码
├── retriever/
│   ├── bm25_retriever.py       # BM25 检索
│   ├── vector_retriever.py     # 向量检索
│   ├── hybrid_retriever.py     # 混合检索
│   └── reranker.py             # BGE Reranker 重排序
├── strategy/
│   ├── direct_search.py        # 直接检索
│   ├── hyde_strategy.py        # HyDE 假设检索
│   ├── sub_query.py            # 子查询分解
│   ├── backtrack.py            # 回溯检索
│   └── multimodal_strategy.py  # 多模态检索
├── router/                     # 3 层路由（rule/similarity/llm）
├── evaluation/
│   ├── evaluator.py            # 检索评估（Precision/Recall/F1/MRR/NDCG）
│   └── ragas_evaluator.py      # RAGAS 评估（faithfulness/relevancy）
├── llm/
│   ├── llm_client.py           # LLM 客户端（OpenAI 兼容 + 流式）
│   └── prompt_template.py      # Prompt 模板管理
├── ui/
│   └── gradio_app.py           # ⭐ API_BASE 端口修正 8001→8000，12 个端点路径同步
├── run.py                      # 启动入口
├── test_data/                  # 测试文档
├── data/                       # 运行时数据（chunks_index.json）
└── docs/                       # 文档
```

### 当前数据库表（MySQL, database=edurag_db）

| 表名 | 用途 | Phase 1 状态 |
|------|------|:--:|
| `documents` | 文档记录 | 原有 |
| `faq` | FAQ 问答对 | 原有 |
| `conversations` | 会话 | 原有 |
| `conversation_messages` | 会话消息 | 原有 |
| `knowledge_bases` | 知识库 | 原有 |
| `kb_documents` | 知识库-文档关联 | 原有 |
| `users` | 用户表（id, username, password_hash, role, display_name） | ⭐ **新增** |
| `feedback` | 反馈表（id, user_id, conversation_id, query, answer, rating, comment） | ⭐ **新增** |

---

## 三、端点路由分配（最终实际状态）

### 3.1 公共端点（routes.py，无需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/query` | 问答查询核心接口 |
| POST | `/api/v1/query/stream` | 流式问答查询 SSE（Gradio 聊天依赖，保留在公共路由） |
| POST | `/api/v1/upload` | 上传文档 |
| GET | `/api/v1/documents` | 文档列表（分页） |
| GET | `/api/v1/stats` | 系统统计信息 |
| GET | `/api/v1/faq` | FAQ 列表（分页） |

### 3.2 学生端（student_routes.py，需 JWT student 角色）

| 方法 | 路径 | 说明 | 类型 |
|------|------|------|:--:|
| POST | `/api/v1/student/login` | 学生登录 | ⭐ 新增 |
| POST | `/api/v1/student/register` | 学生注册 | ⭐ 新增 |
| POST | `/api/v1/student/feedback` | 提交答案反馈 👍👎 | ⭐ 新增 |
| GET | `/api/v1/student/history` | 获取对话历史 | ⭐ 新增 |
| POST | `/api/v1/student/query/citations` | 带内联引用高亮的查询 | 迁移 |
| POST | `/api/v1/student/conversation` | 创建新对话 | 迁移 |
| GET | `/api/v1/student/conversation/{id}` | 获取对话历史 | 迁移 |
| GET | `/api/v1/student/conversations` | 列出当前学生对话（分页） | 迁移 |

### 3.3 管理端（admin_routes.py，需 JWT admin 角色）

| 方法 | 路径 | 说明 | 类型 |
|------|------|------|:--:|
| POST | `/api/v1/admin/login` | 管理员登录 | ⭐ 新增 |
| GET | `/api/v1/admin/stats` | 管理员统计面板（含反馈统计） | ⭐ 新增 |
| POST | `/api/v1/admin/faq/import` | 导入示例 FAQ | 迁移 |
| DELETE | `/api/v1/admin/documents/{doc_id}` | 删除文档 | 迁移 |
| POST | `/api/v1/admin/evaluate` | RAG 检索评估 | 迁移 |
| GET | `/api/v1/admin/evaluate/samples` | 评估样本列表 | 迁移 |
| POST | `/api/v1/admin/evaluate/ragas` | RAGAS 评估 | 迁移 |
| GET | `/api/v1/admin/evaluate/ragas/samples` | RAGAS 样本列表 | 迁移 |
| POST | `/api/v1/admin/kb` | 创建知识库 | 迁移 |
| GET | `/api/v1/admin/kb` | 列出知识库 | 迁移 |
| GET | `/api/v1/admin/kb/search` | 搜索知识库 | 迁移 |
| GET | `/api/v1/admin/kb/{kb_id}` | 获取知识库详情 | 迁移 |
| PUT | `/api/v1/admin/kb/{kb_id}` | 更新知识库 | 迁移 |
| DELETE | `/api/v1/admin/kb/{kb_id}` | 删除知识库 | 迁移 |
| GET | `/api/v1/admin/kb/{kb_id}/stats` | 知识库统计 | 迁移 |
| POST | `/api/v1/admin/kb/{kb_id}/documents` | 添加文档到知识库 | 迁移 |
| GET | `/api/v1/admin/kb/{kb_id}/documents` | 知识库文档列表 | 迁移 |
| DELETE | `/api/v1/admin/kb/{kb_id}/documents/{doc_id}` | 移除文档 | 迁移 |
| GET | `/api/v1/admin/traces` | 追踪记录列表 | 迁移 |
| GET | `/api/v1/admin/traces/{trace_id}` | 追踪详情 | 迁移 |
| POST | `/api/v1/admin/agent/query` | Agentic RAG 查询 | 迁移 |
| POST | `/api/v1/admin/agent/query/stream` | Agent 流式查询 SSE | 迁移 |
| GET | `/api/v1/admin/agent/tools` | Agent 可用工具列表 | 迁移 |
| POST | `/api/v1/admin/multimodal/query` | 多模态查询 | 迁移 |
| POST | `/api/v1/admin/multimodal/query/stream` | 多模态流式查询 SSE | 迁移 |
| POST | `/api/v1/admin/multimodal/upload` | 多模态文档上传 | 迁移 |
| GET | `/api/v1/admin/multimodal/models` | 可用视觉模型列表 | 迁移 |

> **汇总**：公共 6 个 + 学生 8 个 + 管理 27 个 = **共 41 个端点**

---

## 四、各任务执行情况

### 任务 1：users 表 ✅

**文件**：`database/mysql_db.py`

- ✅ `init_tables()` 中新增 `users` 表建表 SQL
- ✅ 新增 `create_user()`, `get_user_by_username()`, `get_user_by_id()`, `list_users()` 4 个方法
- ✅ role 字段取值：`student` / `admin`

### 任务 2：feedback 表 ✅

**文件**：`database/mysql_db.py`

- ✅ `init_tables()` 中新增 `feedback` 表建表 SQL（含外键引用 users.id）
- ✅ 新增 `insert_feedback()`, `get_feedback_stats()` 2 个方法
- ✅ rating 字段取值：`like` / `dislike`

### 任务 3：知识库 CRUD 方法 ✅

**文件**：`database/mysql_db.py`

- ✅ 新增 8 个方法：`create_knowledge_base()`, `list_knowledge_bases()`, `get_knowledge_base()`, `update_knowledge_base()`, `delete_knowledge_base()`, `add_doc_to_kb()`, `remove_doc_from_kb()`, `get_kb_documents()`

### 任务 4：JWT 鉴权模块 ✅

**文件**：`api/auth.py`（新建）

- ✅ `hash_password()` / `verify_password()`：SHA256 密码哈希
- ✅ `create_token()` / `decode_token()`：JWT HS256，24h 过期
- ✅ `get_current_user()`：从 `Authorization: Bearer <token>` 头解析用户
- ✅ `require_admin()` / `require_student()`：角色依赖注入

### 任务 5：路由拆分 ✅

**文件**：`api/student_routes.py`（新建）+ `api/admin_routes.py`（新建）+ `api/routes.py`（精简）

- ✅ 从 routes.py 迁移 30 个端点到 student/admin 路由文件
- ✅ routes.py 保留 6 个公共端点（含恢复的 `/query/stream`）
- ✅ 所有迁移端点的函数体、import 完整保留
- ✅ 管理端点统一加了 `Depends(require_admin)` 鉴权依赖

### 任务 6：路由注册 ✅

**文件**：`api/main.py`

- ✅ 注册 3 个路由器：`router`（公共）、`student_router`、`admin_router`

### 任务 7：管理员初始化脚本 ✅

**文件**：`scripts/init_admin.py`（新建）

- ✅ 默认管理员：admin / admin123
- ✅ 默认测试学生：2024001 / 123456
- ✅ 幂等执行（已存在则跳过）

---

## 五、Gradio 适配（额外完成）

在路由拆分后发现 Gradio UI 调用的端点路径和端口不匹配，同步修复：

| 修复项 | 内容 |
|--------|------|
| `API_BASE` 默认端口 | `8001` → `8000` |
| 端点路径（12 处） | `/evaluate` → `/admin/evaluate`、`/kb/` → `/admin/kb/`、`/agent/query` → `/admin/agent/query` 等 |
| `/query/stream` | 从 student 路由移回公共路由（Gradio 聊天标签页依赖） |

---

## 六、预设账号

| 角色 | 用户名 | 密码 | 说明 |
|------|--------|------|------|
| 管理员 | `admin` | `admin123` | 可访问全部管理端接口 |
| 学生 | `2024001` | `123456` | 可访问学生端接口 |

初始化命令：
```bash
G:\anaconda3\python.exe d:\EduRAG智慧问答系统\scripts\init_admin.py
```

---

## 七、验证结果

| 测试用例 | 结果 |
|----------|:--:|
| 健康检查 | ✅ 200 |
| 管理员登录（正确密码） | ✅ 200 + token |
| 管理员登录（错误密码） | ✅ 401 |
| 学生登录 | ✅ 200 + token |
| 鉴权拦截（无 token） | ✅ 401 |
| 鉴权拦截（学生越权访问管理端） | ✅ 403 |
| 管理员-知识库 CRUD | ✅ 200 |
| 管理员-统计面板 | ✅ 200 |
| 学生-创建/查看对话 | ✅ 200 |
| 学生-提交反馈 | ✅ 200 |
| 公共-文档列表/FAQ/统计 | ✅ 200 |
| 管理员-评估/RAGAS/Agent/多模态 | ✅ 200 |
| 模型评估接口 | ✅ 200（Precision=0.33, Recall=0.22, MRR=0.4） |
| RAGAS 评估接口 | ✅ 200（Faithfulness=0.53, Relevancy=0.93） |

---

## 八、Phase 2 规划（待执行）

### 目标
将单页面 Gradio UI 拆分为两个独立前端应用：学生端 + 管理端

### 待拆分的 Gradio 标签页

| 当前标签页 | 目标归属 |
|-----------|----------|
| 💬 智能问答 | 学生端 |
| 📚 引用高亮 | 学生端 |
| 📜 对话历史 | 学生端 |
| 📤 文档上传 | 管理端 |
| 📊 模型评估 | 管理端 |
| 📈 RAGAS评估 | 管理端 |
| 📁 知识库管理 | 管理端 |
| 🕵️ Langfuse追踪 | 管理端 |
| 🤖 Agentic RAG | 管理端 |
| 🖼️ 多模态RAG | 管理端 |

### 关键任务
1. 新建 `ui/student_app.py`（端口 7860）：登录 → 问答/引用/历史/反馈
2. 新建 `ui/admin_app.py`（端口 7861）：登录 → 上传/评估/知识库/追踪/Agent/多模态
3. 两个应用均需 token 持久化 + 自动注入 `Authorization` 头
4. `run.py` 支持 `--mode ui-student` / `--mode ui-admin` / `--mode ui-all` 新参数
5. 可复用现有 Gradio 代码，按标签页拆分为独立文件
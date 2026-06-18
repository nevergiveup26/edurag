# EduRAG 智慧问答系统

基于 RAG（Retrieval-Augmented Generation）技术的智慧教育问答平台，面向k12学生，提供智能问答、作业批改、拍照搜题、错题集等学习工具。

## 系统概览

| 角色 | 功能 |
|------|------|
| **学生端** | 智能问答、作业批改、拍照搜题、错题集（艾宾浩斯复习）、历史会话 |
| **管理端** | 数据大盘、知识库上传、批量评估、RAGAS 评测、评估历史、知识库管理、调用链追踪、可视化分析 |

## 技术栈

### 前端
- **框架**: Vue 3 + Vite
- **UI 组件库**: Element Plus
- **状态管理**: Pinia
- **路由**: Vue Router 4
- **图表**: ECharts / vue-echarts
- **Markdown 渲染**: marked + highlight.js + KaTeX

### 后端
- **框架**: FastAPI + Uvicorn
- **Agent 编排**: LangGraph（ReAct Chat Agent + StateGraph Grade Agent）
- **LLM**: 阿里云 DashScope 通义千问（qwen-max / qwen-plus），OpenAI 兼容 API
- **Embedding**: DashScope text-embedding-v4（1024维）
- **向量库**: Milvus 2.3
- **关系库**: MySQL 8.0
- **缓存**: Redis 7
- **OCR**: DashScope qwen-vl-ocr

### 基础设施
- **容器化**: Docker + Docker Compose
- **可观测性**: LangFuse 全链路追踪
- **评估**: 统一评测框架（检索+生成+LLM 评判）

## 快速开始

### Docker 一键部署（推荐）

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

# 2. 启动所有服务（MySQL + Milvus + Redis + LangFuse + 应用）
docker-compose up -d

# 3. 访问
# 前端:    http://localhost:5173
# API:     http://localhost:8000
# API 文档: http://localhost:8000/docs
# LangFuse: http://localhost:3000
```

### 手动安装

#### 1. 环境要求

- Python 3.10+
- Node.js 18+
- MySQL 8.0+
- Milvus 2.3+
- Redis 7+

#### 2. 后端

```bash
cd EduRAG智慧问答系统

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

# 初始化管理员账号
python scripts/init_admin.py

# 启动 API 服务
python run.py --host 0.0.0.0 --port 8000 --reload
```

#### 3. 前端

```bash
cd frontend
npm install
npm run dev      # 开发模式，默认 http://localhost:5173
npm run build    # 生产构建
```

## 项目结构

```
EduRAG智慧问答系统/
├── api/                       # FastAPI 接口层
│   ├── main.py                # 应用入口 + 生命周期管理
│   ├── routes.py              # 公共路由
│   ├── student_routes.py      # 学生端路由
│   ├── admin_routes.py        # 管理端路由
│   ├── agent_routes.py        # Agent 路由
│   └── auth.py                # JWT 认证模块
├── langgraph_agent/           # LangGraph Agent 编排
│   ├── chat_agent.py          # 智能问答 Agent（ReAct）
│   ├── grade_agent.py         # 作业批改 Agent（StateGraph）
│   ├── retriever.py           # LangChain 检索器适配
│   ├── tools.py               # Agent 工具集（10 个工具）
│   └── model.py               # LLM 模型封装
├── agent/                     # 批改引擎
│   └── grading.py             # 统一批改逻辑
├── core/                      # 核心模块
│   ├── config_manager.py      # 配置管理器（单例）
│   ├── models.py              # 数据模型定义
│   ├── stream_events.py       # SSE 流事件定义
│   └── logger.py              # 日志模块
├── database/                  # 数据库层
│   ├── mysql_db.py            # MySQL（12 张表）
│   ├── milvus_db.py           # Milvus 向量库
│   ├── redis_cache.py         # Redis 缓存
│   └── chunk_store.py         # Chunk JSONL 存储
├── data_processor/            # 数据处理流水线
│   ├── document_loader.py     # 文档加载（PDF/Word/TXT/MD/CSV/JSON）
│   ├── document_splitter.py   # 智能分块
│   ├── query_rewriter.py      # Query 改写（代词消解/短句扩展）
│   ├── multi_query.py         # 多查询生成
│   ├── context_compressor.py  # 上下文压缩
│   ├── guardrails.py          # 安全护栏（幻觉检测/引用校验）
│   ├── metadata_extractor.py  # 元数据提取（学科/年级/文档类型）
│   ├── vectorizer.py          # DashScope 文本向量化
│   ├── vision_encoder.py      # CLIP 图片向量化
│   ├── multimodal_loader.py   # 多模态文档加载
│   └── graph_builder.py       # 知识图谱构建
├── router/                    # 智能查询路由
│   ├── query_router.py        # 三层路由（规则+相似度+LLM）
│   ├── rule_router.py         # 规则路由
│   ├── similarity_router.py   # 相似度路由
│   └── llm_router.py          # LLM 路由
├── strategy/                  # 检索策略
│   ├── base_strategy.py       # 策略基类
│   ├── hyde_strategy.py       # HyDE 策略
│   ├── sub_query_strategy.py  # 子查询分解策略
│   └── backtrack_strategy.py  # 回溯检索策略
├── retriever/                 # 检索模块
│   ├── bm25_retriever.py      # BM25 稀疏检索
│   ├── vector_retriever.py    # Milvus 向量检索
│   ├── hybrid_retriever.py    # 混合检索 + RRF 融合
│   └── reranker.py            # 重排序
├── evaluation/                # 评估模块
│   ├── metrics/               # 评估指标
│   │   ├── retrieval.py       # 检索指标（Precision/Recall/MRR/NDCG）
│   │   ├── generation.py      # 生成指标（BLEU/ROUGE/关键词）
│   │   └── llm_judge.py       # LLM 评判（忠实度/相关性/正确性）
│   ├── unified_evaluator.py   # 统一评估器
│   ├── evaluator.py           # 评估器（废弃，委托给 unified_evaluator）
│   ├── report.py              # HTML 评估报告
│   └── ablation.py            # 消融实验
├── monitoring/                # 可观测性
│   └── langfuse_tracer.py     # LangFuse 全链路追踪
├── llm/                       # LLM 客户端
│   ├── llm_client.py          # 统一 LLM 客户端（OpenAI 兼容）
│   └── ocr_client.py          # DashScope OCR
├── kb/                        # 知识库管理
│   └── knowledge_base.py      # 知识库 CRUD
├── config/                    # 配置文件
│   ├── config.ini             # 系统配置
│   └── logging_config.py      # 日志配置
├── frontend/                  # Vue 3 前端
│   └── src/
│       ├── views/student/     # 学生端页面
│       └── views/admin/       # 管理端页面
├── scripts/                   # 工具脚本
├── tests/                     # 测试
├── docker/                    # Docker 初始化脚本
│   └── init.sql               # MySQL 建表语句
├── docker-compose.yml         # Docker Compose 编排
├── Dockerfile                 # 应用镜像
├── requirements.txt           # Python 依赖
└── README.md
```

## API 概览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/student/login` | 学生登录 |
| POST | `/admin/login` | 管理员登录 |
| POST | `/student/register` | 学生注册 |

### 学生端

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/student/agent/chat` | 智能问答（SSE 流式） |
| POST | `/student/agent/grade` | 作业批改（SSE 流式） |
| GET  | `/student/agent/tools` | 获取可用工具列表 |
| GET  | `/student/conversations` | 会话列表 |
| POST | `/student/conversation` | 创建会话 |
| GET  | `/student/conversation/{id}` | 会话详情（含历史消息） |
| DELETE | `/student/conversation/{id}` | 删除会话 |
| PATCH | `/student/conversation/{id}/pin` | 置顶/取消置顶 |
| POST | `/student/photo-search` | 拍照搜题 |
| GET  | `/student/wrong-book` | 错题集列表 |
| POST | `/student/wrong-book` | 添加错题 |
| DELETE | `/student/wrong-book/{id}` | 删除错题 |

### 管理端

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/admin/dashboard` | 数据大盘 |
| POST | `/admin/upload` | 上传文档到知识库 |
| POST | `/admin/evaluate/run` | 统一评测 |
| GET  | `/admin/eval-history` | 评估历史 |
| GET  | `/admin/knowledge` | 知识库管理 |
| GET  | `/admin/traces` | 调用链追踪 |

## 检索策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| direct | 直接使用用户查询进行检索 | 简单明确的问题 |
| hyde | 生成假设性文档后进行检索 | 需要假设性辅助的复杂问题 |
| sub_query | 将查询分解为子查询分别检索 | 多角度回答的复杂问题 |
| backtrack | 多轮检索与答案验证 | 需要多轮搜索的复杂问题 |

## 配置说明

项目使用 `.env` 文件 + `config/config.ini` 双层配置，环境变量优先级更高。

```env
# 阿里云 DashScope（必填）
DASHSCOPE_API_KEY=sk-your-dashscope-api-key

# Tavily 网络搜索（可选）
TAVILY_API_KEY=tvly-your-tavily-api-key

# LangFuse 可观测性（可选）
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://us.cloud.langfuse.com
LANGFUSE_ENABLED=true
```

数据库连接等基础设施配置在 `config/config.ini` 中，支持 `${ENV_VAR}` 环境变量插值。

## 常见问题

**Q: 启动时提示数据库连接失败？**
A: 确保 MySQL、Milvus、Redis 服务已启动，检查 `config/config.ini` 中的连接配置。

**Q: LLM 调用失败？**
A: 确认 `.env` 中 `DASHSCOPE_API_KEY` 已正确配置，且账户有可用额度。

**Q: 前端代理报错？**
A: 前端开发服务器通过 Vite proxy 将 `/api` 转发到 `http://127.0.0.1:8000`，确保后端已启动。

**Q: 如何提高问答准确度？**
A: 1) 上传高质量文档到知识库 2) 尝试不同检索策略 3) 调整 top_k 和相似度阈值。

## 许可证

本项目仅供学习和研究使用。

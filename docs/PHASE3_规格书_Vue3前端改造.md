# PHASE3 规格书 — Vue 3 + Vite 前端改造

> 版本: v1.0  
> 日期: 2026-06-09  
> 状态: ✅ 前置准备完成，可进入功能开发

---

## 一、改造目标

将原有的 Gradio 前端（学生端 `student_app.py` + 管理端 `admin_app.py`）替换为现代化的 **Vue 3 + Vite + Element Plus** 单页应用（SPA），提供专业级的 UI/UX 体验。

### 原 Gradio 前端痛点
- 界面简陋、样式单一，无法自定义
- 不支持真正的响应式布局
- 状态管理混乱（大量 `gr.State` 手动传递）
- 交互体验差（整页刷新、无路由）
- 不可扩展（难以添加新页面/新交互）

### Vue 3 前端优势
- 现代化 UI 框架 + 企业级组件库（Element Plus）
- SPA 路由（Vue Router），页面切换流畅
- 集中状态管理（Pinia）
- SSE 流式响应天然支持
- ECharts 可视化（仪表盘、评测图表）
- Markdown + 代码高亮渲染
- 响应式设计，适配多端

---

## 二、技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 框架 | Vue 3 (Composition API) | ^3.5 |
| 构建 | Vite | ^6.0 |
| UI 库 | Element Plus | ^2.9 |
| 图标 | @element-plus/icons-vue | ^2.3 |
| 路由 | Vue Router | ^4.4 |
| 状态管理 | Pinia | ^2.2 |
| HTTP | Axios | ^1.7 |
| 图表 | ECharts + vue-echarts | ^5.5 / ^7.0 |
| Markdown | marked + highlight.js | ^14.1 / ^11.10 |

---

## 三、项目结构

```
frontend/
├── index.html                     # 入口 HTML
├── package.json                   # 依赖声明
├── vite.config.js                 # Vite 配置（代理、别名、Element Plus 自动导入）
├── public/
│   └── favicon.svg
└── src/
    ├── main.js                    # 应用入口（注册 Vue/Pinia/Router/ElementPlus）
    ├── App.vue                    # 根组件（<router-view />）
    ├── api/
    │   ├── request.js             # Axios 实例 + JWT 拦截器
    │   ├── index.js               # 学生端 + 公共 API（16 个接口）
    │   └── admin.js               # 管理端 API（16 个接口）
    ├── stores/
    │   ├── auth.js                # 认证状态（登录/登出/角色/token）
    │   └── chat.js                # 聊天状态（会话/消息）
    ├── router/
    │   └── index.js               # 路由表 + 导航守卫
    ├── assets/
    │   └── styles/
    │       └── main.css           # 全局样式 + CSS 变量
    └── views/
        ├── Login.vue              # 统一登录（学生/管理员标签切换 + 注册弹窗）
        ├── NotFound.vue           # 404 页面
        ├── student/
        │   ├── StudentLayout.vue  # 学生端布局（侧边栏 + 路由出口）
        │   ├── ChatView.vue       # 智能问答（SSE 流式 + 多模态上传）
        │   ├── HistoryView.vue    # 对话历史（列表 + 详情抽屉）
        │   └── VisualizeView.vue  # 检索可视化（统计 + 检索演示）
        └── admin/
            ├── AdminLayout.vue    # 管理端布局（侧边栏 + 子菜单 + 路由出口）
            ├── DashboardView.vue  # 仪表盘（统计卡片 + ECharts 图表）
            ├── UploadView.vue     # 文档上传（拖拽上传 + 文档列表管理）
            ├── EvaluateView.vue   # 检索评测（指标卡片 + 图表 + 样例）
            ├── RagasView.vue      # RAGAS 评测（指标选择 + 结果展示）
            ├── KnowledgeView.vue  # 知识库（左右分栏 CRUD）
            ├── TracesView.vue     # 调用链追踪（列表 + 详情弹窗）
            ├── AgentView.vue      # Agent 对话（工具展示 + 聊天）
            └── MultimodalView.vue # 多模态管理（图片上传 + 查询 + 模型列表）
```

---

## 四、路由设计

| 路径 | 名称 | 组件 | 角色 | 守卫 |
|------|------|------|------|------|
| `/` | - | 重定向到 /login | - | - |
| `/login` | Login | Login.vue | - | guest（已登录则跳转） |
| `/student/chat` | StudentChat | ChatView.vue | student | requiresAuth |
| `/student/history` | StudentHistory | HistoryView.vue | student | requiresAuth |
| `/student/visualize` | StudentVisualize | VisualizeView.vue | student | requiresAuth |
| `/admin/dashboard` | AdminDashboard | DashboardView.vue | admin | requiresAuth |
| `/admin/upload` | AdminUpload | UploadView.vue | admin | requiresAuth |
| `/admin/evaluate` | AdminEvaluate | EvaluateView.vue | admin | requiresAuth |
| `/admin/ragas` | AdminRagas | RagasView.vue | admin | requiresAuth |
| `/admin/knowledge` | AdminKnowledge | KnowledgeView.vue | admin | requiresAuth |
| `/admin/traces` | AdminTraces | TracesView.vue | admin | requiresAuth |
| `/admin/agent` | AdminAgent | AgentView.vue | admin | requiresAuth |
| `/admin/multimodal` | AdminMultimodal | MultimodalView.vue | admin | requiresAuth |
| `/:pathMatch(.*)*` | NotFound | NotFound.vue | - | - |

### 导航守卫逻辑
1. `requiresAuth` → 无 token 则跳 `/login`
2. `role` 不匹配 → 跳对应的默认首页
3. `guest` + 已有 token → 按角色跳首页

---

## 五、API 代理

Vite 开发服务器将 `/api` 前缀的请求代理到 FastAPI 后端：

```js
// vite.config.js
proxy: {
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
}
```

所有 API 调用统一通过 Axios 实例 (`baseURL: '/api/v1'`)，自动注入 JWT Bearer Token：

```
Authorization: Bearer <edurag_token>
```

401 → 清除 token，跳转登录页  
403 → 提示"权限不足"  
500 → 提示服务器错误

---

## 六、状态管理（Pinia）

### authStore
- `token` / `user` — localStorage 持久化
- `isLoggedIn` / `isAdmin` / `isStudent` / `username` / `role` — 计算属性
- `login(role, username, password)` — 调用后端 API，写入 store + localStorage
- `logout()` — 清除 token 和 user

### chatStore（预留）
- `conversations` / `currentConversationId` / `messages`
- `addMessage(role, content)` / `clearMessages()`

---

## 七、页面功能矩阵

### 学生端
| 页面 | 状态 | 核心功能 |
|------|------|----------|
| Login | ✅ | 学生/管理员标签切换、登录、注册弹窗 |
| ChatView | ✅ | SSE 流式问答、多模态图片上传+查询、策略设置、Markdown 渲染 |
| HistoryView | ✅ | 对话列表分页、详情抽屉查看、删除 |
| VisualizeView | ✅ | 知识库统计卡片、检索演示 |

### 管理端
| 页面 | 状态 | 核心功能 |
|------|------|----------|
| Login | ✅ | 同上 |
| DashboardView | ✅ | 统计卡片、ECharts 趋势图/饼图、最近文档表 |
| UploadView | ✅ | 拖拽上传、文件列表、搜索、删除 |
| EvaluateView | ✅ | 评测运行、指标卡片、base64 图表、样例折叠 |
| RagasView | ✅ | RAGAS 评测运行、指标选择、结果表格 |
| KnowledgeView | ✅ | 知识库 CRUD、左右分栏、文档管理 |
| TracesView | ✅ | 调用记录表格、详情弹窗（步骤时间线+检索结果）|
| AgentView | ✅ | 可用工具展示、Agent 对话、Markdown 渲染 |
| MultimodalView | ✅ | 图片上传与查询、模型列表 |

---

## 八、后续 TODO

### 第一优先级（核心功能完善）
- [ ] ChatView：完善多模态 SSE 流式响应（当前多模态走非流式）
- [ ] ChatView：对话历史持久化（与后端 conversations API 对接）
- [ ] HistoryView：删除对话后端 API 对接
- [ ] DashboardView：真实数据替换模拟数据

### 第二优先级（体验优化）
- [ ] ChatView：添加引用来源卡片展示
- [ ] 全局：暗色模式切换
- [ ] 全局：多标签页（TabView）支持
- [ ] 管理端：批量操作（批量删除文档/知识库）

### 第三优先级（高级功能）
- [ ] 学生端：知识图谱可视化
- [ ] 管理端：导出评测报告（PDF/Excel）
- [ ] 管理端：系统设置页面（嵌入模型、检索参数配置）
- [ ] PWA 支持

---

## 九、运行说明

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖（已完成）
npm install

# 3. 启动开发服务器（已完成，运行在 http://localhost:5173）
npm run dev

# 4. 确保 FastAPI 后端运行在 http://127.0.0.1:8000

# 5. 生产构建
npm run build     # 输出到 dist/
```

---

## 十、预设测试账户

| 角色 | 用户名 | 密码 | 默认首页 |
|------|--------|------|----------|
| 学生 | 2024001 | 123456 | /student/chat |
| 管理员 | admin | admin123 | /admin/dashboard |

---

## 十一、与 Gradio 版本的对比

| 维度 | Gradio 版本 | Vue 3 版本 |
|------|------------|-----------|
| UI 美观度 | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 响应速度 | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 路由 | 无（手动切换端口） | 完整 SPA 路由 |
| SSE 流式 | 部分支持 | 完整支持 |
| 代码高亮 | 不支持 | highlight.js |
| 图表 | matplotlib 静态图 | ECharts 交互图 |
| 可扩展性 | 低 | 高（组件化） |
| 文件大小 | 大（Gradio 依赖） | 小（Tree-shaking） |

---

> ✅ **前置准备完成**：项目 scaffold 搭建、依赖安装、14 个页面（含布局）全部创建、Vite 开发服务器运行正常。
> 当前可在 `http://localhost:5173` 打开前端，配合 `http://127.0.0.1:8000` 后端 API 进行完整功能测试。
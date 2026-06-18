# 智能查询路由 — 三层架构设计规格

> 日期: 2026-06-17
> 状态: 待审查

## 1. 目标

在 chat 模式下，根据用户查询的复杂程度，自动选择最优检索策略（direct/hyde/sub_query/backtrack），替代当前"所有查询走同一流程"的粗放模式。通过三层递进路由（规则 → 相似度 → LLM），在延迟和准确率之间取得平衡。

## 2. 范围

- **分发范围**：仅分发到 4 种检索策略（direct/hyde/sub_query/backtrack），不涉及批改模式和多模态模式
- **插入位置**：`agent_routes.py` 中，调用 `stream_agent_response` 之前，作为独立前置模块
- **Layer 2 数据源**：预设锚点示例库（每种策略 5 条），不依赖历史数据积累
- **Layer 3 模型**：复用 `get_fast_llm()`（qwen-turbo）

## 3. 架构

```
用户查询
    │
    ▼
┌─────────────┐
│ agent_routes │ 接收 query + images
│  .py         │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│           QueryRouter (新增模块)             │
│                                             │
│  Layer 1: RuleRouter      → 命中？→ 策略名  │
│  Layer 2: SimilarityRouter → 命中？→ 策略名  │
│  Layer 3: LLMRouter       → 兜底 → 策略名   │
└──────────────────┬──────────────────────────┘
                   │ strategy_name
                   ▼
┌─────────────┐
│ chat_agent  │ 根据 strategy_name 走不同检索分支
│  .py        │
└─────────────┘
```

## 4. 新增文件

| 文件 | 职责 |
|------|------|
| `router/__init__.py` | 导出 `QueryRouter` 统一入口 |
| `router/rule_router.py` | Layer 1: 关键词 + 正则规则匹配 |
| `router/similarity_router.py` | Layer 2: 向量相似度 + 锚点示例库 |
| `router/llm_router.py` | Layer 3: qwen-turbo 意图分类 |
| `router/query_router.py` | 三层串联编排，缓存和降级逻辑 |

## 5. 修改文件

| 文件 | 改动 |
|------|------|
| `api/agent_routes.py` | 调用 `QueryRouter.route()` 获取策略，传入 `stream_agent_response` |
| `langgraph_agent/chat_agent.py` | `stream_agent_response` 新增 `strategy` 参数，内部根据策略走不同检索分支 |

## 6. Layer 1 — 规则路由（RuleRouter）

**延迟**: 0ms，零成本
**预期命中率**: ~60%

### 匹配规则表

| 优先级 | 名称 | 触发条件 | 目标策略 |
|--------|------|----------|----------|
| 1 | 短事实查询 | 长度 ≤ 15 字 且 含"是谁/什么是/定义/公式/多少/哪个/哪里/哪年/谁" | `direct` |
| 2 | 对比分析 | 含"区别/对比/比较/哪个更好/vs/有什么不同" | `hyde` |
| 3 | 多步推理 | 含"先...再.../然后/步骤/怎么做/怎么解/如何/规划/设计" | `sub_query` |
| 4 | 深度研究 | 含"为什么/原因/原理/证明/推导/怎么来的" | `backtrack` |

### 接口

```python
class RuleRouter:
    def route(self, query: str) -> Optional[str]:
        """返回策略名或 None（未命中）"""
```

### 实现要点

- 按优先级顺序依次匹配，第一个命中即返回
- 规则 1 有长度限制（≤ 15 字），其余规则无长度限制
- 使用 `re.search` 做正则匹配，支持中文关键词

## 7. Layer 2 — 相似度路由（SimilarityRouter）

**延迟**: ~50ms（embedding API 调用）
**预期命中率**: ~30%（累计 90%）
**相似度阈值**: 0.75

### 锚点示例库

| 策略 | 锚点示例 |
|------|----------|
| `direct` | "什么是光合作用"、"牛顿第一定律的内容"、"中国的首都是哪里"、"圆的面积公式是什么"、"抗日战争是哪一年开始的" |
| `hyde` | "内燃机和电动机的优缺点对比"、"文言文和白话文有什么区别"、"线上教育和线下教育哪个更好"、"古典音乐和流行音乐的比较"、"民主制度和专制制度的区别" |
| `sub_query` | "先查一下秦始皇统一六国的过程，再分析对后世的影响"、"帮我分析这道二次函数的题怎么做"、"如何写一篇关于环保的议论文，分几个步骤"、"设计一个科学实验验证光合作用需要光"、"怎么规划一个月的期末复习计划" |
| `backtrack` | "为什么天空是蓝色的，背后的物理原理是什么"、"黑洞的形成原因和霍金辐射的推导过程"、"达尔文进化论的证据和论证逻辑"、"为什么说熵增定律是宇宙的终极规律"、"量子纠缠的原理是什么，为什么爱因斯坦说它是鬼魅般的超距作用" |

### 接口

```python
class SimilarityRouter:
    def __init__(self, embedding_client):
        """初始化时将所有锚点向量化，存入内存"""
    
    def route(self, query: str) -> Optional[str]:
        """返回策略名或 None（未命中，相似度 < 0.75）"""
```

### 实现要点

- 使用 DashScope `text-embedding-v3` 做向量化
- 初始化时一次性将所有 20 条锚点向量化，存入内存（numpy 数组）
- 查询时计算余弦相似度，取 top-1
- 相似度 < 0.75 返回 None，交给 Layer 3

## 8. Layer 3 — LLM 路由（LLMRouter）

**延迟**: ~300-500ms
**成本**: 极低（qwen-turbo）
**命中率**: 100%（兜底，分类失败时降级为 direct）

### 提示词

```
你是一个查询分类器。请将以下用户查询分类到 4 种检索策略之一：

- direct：简单事实查询，直接检索即可回答
- hyde：对比分析类问题，需要生成假设文档辅助检索
- sub_query：多步推理或复合问题，需要分解为子问题
- backtrack：深层原理类问题，需要多轮检索和验证

用户查询：{query}

请仅返回 JSON：{"strategy": "策略名", "confidence": 0.0~1.0}
```

### 接口

```python
class LLMRouter:
    def __init__(self, fast_llm):
        """使用 get_fast_llm() 返回的 qwen-turbo"""
    
    def route(self, query: str) -> str:
        """返回策略名，必定返回（失败时降级为 direct）"""
```

### 实现要点

- 使用 instructor 库的 `response_model` 模式确保 JSON 格式
- 超时 5 秒，超时降级为 `direct`
- 分类置信度 < 0.5 时降级为 `direct`
- LRU 缓存（最多 500 条），相同查询直接返回

## 9. 统一入口 — QueryRouter

```python
class QueryRouter:
    def __init__(self):
        self.rule_router = RuleRouter()
        self.similarity_router = SimilarityRouter(get_embedding_client())
        self.llm_router = LLMRouter(get_fast_llm())
        # LRU 缓存: query_text → strategy_name
        self._cache = {}  # 最多 500 条
    
    def route(self, query: str) -> str:
        """三层递进路由，返回策略名"""
        # 1. 查缓存
        if query in self._cache:
            return self._cache[query]
        
        # 2. Layer 1: 规则
        result = self.rule_router.route(query)
        if result:
            self._cache_result(query, result)
            return result
        
        # 3. Layer 2: 相似度
        result = self.similarity_router.route(query)
        if result:
            self._cache_result(query, result)
            return result
        
        # 4. Layer 3: LLM 兜底
        result = self.llm_router.route(query)
        self._cache_result(query, result)
        return result
```

## 10. 集成点改动

### agent_routes.py

```python
# agent_query_stream 中，调用 stream_agent_response 之前
from router.query_router import get_query_router
router = get_query_router()
strategy = router.route(request.query)

async for sse_str in stream_agent_response(
    agent, request.query, config=config, history=history,
    conversation_id=conversation_id, user_id=request.user_id,
    images=request.images,
    strategy=strategy,  # 新增
):
```

### chat_agent.py

```python
async def stream_agent_response(
    agent, user_message, config=None, history=None,
    conversation_id=None, user_id=None,
    images=None,
    strategy: str = "direct",  # 新增
):
    # 根据 strategy 修改 system prompt 中的检索规则
    # 或直接选择不同的检索执行路径
```

## 11. 错误处理

| 场景 | 处理 |
|------|------|
| Layer 1 未命中 | 正常流转 Layer 2 |
| Layer 2 embedding API 超时 | 跳过 Layer 2，直接走 Layer 3 |
| Layer 2 相似度低于阈值 | 返回 None，流转 Layer 3 |
| Layer 3 LLM 超时（5秒） | 降级为 `direct` |
| Layer 3 置信度 < 0.5 | 降级为 `direct` |
| Layer 3 返回格式异常 | 降级为 `direct` |
| 全链路异常 | 兜底 `direct`，记录日志 |

## 12. 测试要点

- 单元测试：每种规则的正则匹配覆盖
- 单元测试：锚点相似度匹配的阈值边界
- 单元测试：LLM 分类的 JSON 解析和降级逻辑
- 集成测试：三层递进流转的正确性
- 端到端测试：router → agent → 回答的完整链路

## 13. 非目标

- 不涉及批改模式（grade）和多模态模式（multimodal）的路由
- 不涉及前端改动
- 不涉及历史数据积累和自学习（后续迭代）
- 不涉及策略的具体实现（hyde/sub_query/backtrack 的另一期工作）
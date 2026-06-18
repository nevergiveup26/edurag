# 四种检索策略实现 — 设计规格

> 日期: 2026-06-17
> 状态: 待审查

## 1. 目标

实现 direct、hyde、sub_query、backtrack 四种检索策略的具体执行逻辑。direct 策略保持现有 ReAct 流程不变，其余三种策略在 agent 调用前做预处理检索，将上下文注入 system prompt，agent 直接回答而不走 ReAct 工具调用。

## 2. 架构

```
stream_agent_response(query, strategy, ...)
    │
    ├─ strategy == "direct" ──→ 现有 ReAct 流程（不动）
    │
    └─ strategy != "direct" ──→ strategy/ 预处理
        │
        ├─ "hyde"      → HyDEStrategy.execute(query, retriever, llm)
        ├─ "sub_query" → SubQueryStrategy.execute(query, retriever, llm)
        └─ "backtrack" → BacktrackStrategy.execute(query, retriever, llm, web_search_fn)
        │
        └─ 返回: {context: str, metadata: dict}
              │
              ▼
        注入 system prompt 尾部
        │
        ▼
        单次 LLM 调用回答（不调用 tool）
```

## 3. 新增文件

| 文件 | 职责 |
|------|------|
| `strategy/__init__.py` | 导出 `execute_strategy` 统一入口 |
| `strategy/base_strategy.py` | 抽象基类，定义 `execute()` 接口 |
| `strategy/hyde_strategy.py` | HyDE 策略：生成假设文档 → 检索 |
| `strategy/sub_query_strategy.py` | 子查询策略：分解 → 分别检索 → 拼接 |
| `strategy/backtrack_strategy.py` | 回溯策略：检索 → 评估 → 换源重检 |

## 4. 修改文件

| 文件 | 改动 |
|------|------|
| `langgraph_agent/chat_agent.py` | `stream_agent_response` 中新增策略分支：`strategy != "direct"` 时调用 `execute_strategy`，注入上下文 |

## 5. HyDE 策略

### 流程

```
用户查询 → LLM 生成假设文档 → 用假设文档检索 → 检索结果 + 原始查询 → LLM 直接回答
```

### 核心思想

"假设文档"比"问题"更接近向量库中真实文档的分布，检索命中率更高。

### 接口

```python
class HyDEStrategy(BaseStrategy):
    async def execute(self, query: str, retriever, llm) -> StrategyResult:
        # 1. LLM 生成假设文档
        hyde_doc = llm.chat([
            {"role": "user", "content": HYDE_TEMPLATE.format(question=query)}
        ])
        # 2. 用假设文档检索（而非原始 query）
        results = retriever.search(hyde_doc, top_k=5)
        # 3. 拼接上下文
        context = self._format_context(results)
        return StrategyResult(
            context=context,
            metadata={"hyde_doc": hyde_doc[:200]}
        )
```

### 使用的提示词模板

`llm/prompt_template.py` 中的 `HYDE_TEMPLATE` 和 `generate_hyde_prompt()`。

## 6. 子查询分解策略

### 流程

```
用户查询 → LLM 分解子问题 → 逐个子问题检索 → 拼接所有结果 → LLM 综合回答
```

### 关键约束

- 每个子问题 top_k=3（控制上下文长度）
- 子问题最多 5 个（防止过度分解）
- 检索结果按子问题分组标注

### 接口

```python
class SubQueryStrategy(BaseStrategy):
    async def execute(self, query: str, retriever, llm) -> StrategyResult:
        # 1. LLM 分解
        raw = llm.chat([
            {"role": "user", "content": DECOMPOSE_TEMPLATE.format(question=query)}
        ])
        sub_queries = json.loads(raw)
        
        # 2. 逐个子问题检索
        all_contexts = []
        for sq in sub_queries[:5]:
            results = retriever.search(sq, top_k=3)
            ctx = self._format_context(results)
            all_contexts.append(f"[子问题: {sq}]\n{ctx}")
        
        # 3. 拼接
        context = "\n\n---\n\n".join(all_contexts)
        return StrategyResult(
            context=context,
            metadata={"sub_queries": sub_queries}
        )
```

### 使用的提示词模板

`llm/prompt_template.py` 中的 `DECOMPOSE_TEMPLATE` 和 `generate_decompose_prompt()`。

## 7. 回溯检索策略

### 流程

```
第 1 轮：本地知识库检索 → LLM 质量评估
    ├─ 评分 ≥ 0.6 → 直接用本地结果
    └─ 评分 < 0.6 → LLM 优化查询 → 第 2 轮：tavily_web_search 联网搜索 → 合并结果
```

### 关键参数

- 最多 2 轮
- 质量阈值 0.6
- 第 2 轮切换搜索源为 tavily_web_search

### 接口

```python
class BacktrackStrategy(BaseStrategy):
    MAX_ROUNDS = 2
    QUALITY_THRESHOLD = 0.6

    async def execute(self, query: str, retriever, llm, web_search_fn) -> StrategyResult:
        all_contexts = []
        
        # 第 1 轮：本地检索
        results = retriever.search(query, top_k=5)
        context_1 = self._format_context(results)
        all_contexts.append("[本地知识库检索结果]\n" + context_1)
        
        # 质量评估
        score = self._evaluate_quality(query, context_1, llm)
        if score >= self.QUALITY_THRESHOLD:
            return StrategyResult(
                context=context_1,
                metadata={"rounds": 1, "score": score}
            )
        
        # 第 2 轮：优化查询 + 联网搜索
        refined_query = self._refine_query(query, context_1, llm)
        web_results = await web_search_fn(refined_query)
        context_2 = self._format_web_results(web_results)
        all_contexts.append("[联网搜索结果]\n" + context_2)
        
        return StrategyResult(
            context="\n\n---\n\n".join(all_contexts),
            metadata={"rounds": 2, "score": score, "refined_query": refined_query}
        )
```

### 使用的提示词模板

`llm/prompt_template.py` 中的 `QUALITY_EVAL_TEMPLATE`、`QUERY_REFINE_TEMPLATE` 及对应生成方法。

## 8. 统一入口

```python
# strategy/__init__.py
from strategy.hyde_strategy import HyDEStrategy
from strategy.sub_query_strategy import SubQueryStrategy
from strategy.backtrack_strategy import BacktrackStrategy

_strategies = {
    "hyde": HyDEStrategy(),
    "sub_query": SubQueryStrategy(),
    "backtrack": BacktrackStrategy(),
}

async def execute_strategy(strategy: str, query: str, retriever, llm, web_search_fn=None) -> StrategyResult:
    if strategy == "direct":
        return None  # direct 不需要预处理
    impl = _strategies.get(strategy)
    if not impl:
        return None
    return await impl.execute(
        query=query,
        retriever=retriever,
        llm=llm,
        web_search_fn=web_search_fn,
    )
```

## 9. 数据模型

```python
@dataclass
class StrategyResult:
    context: str          # 检索到的上下文，注入 system prompt
    metadata: dict        # 策略执行元数据，记录到 LangFuse
```

## 10. chat_agent.py 改动

在 `stream_agent_response` 中，消息构建阶段之后插入策略分支：

```python
# 策略预处理（非 direct 策略）
strategy_context = None
if strategy != "direct":
    from strategy import execute_strategy
    from langgraph_agent.tools import _provider
    strategy_result = await execute_strategy(
        strategy=strategy,
        query=user_message,
        retriever=_provider._retriever,
        llm=_provider._llm_client,
        web_search_fn=_tavily_search,
    )
    if strategy_result:
        strategy_context = strategy_result.context
        # 注入到 system prompt 尾部
        system_prompt = system_prompt + "\n\n【系统已检索到的参考资料】\n" + strategy_context
        # 创建不带 tool 的 agent（直接回答）
        agent = create_chat_agent(model=model, tools=[final_answer], system_prompt=system_prompt)
```

## 11. 错误处理

| 场景 | 处理 |
|------|------|
| HyDE 生成失败 | 降级为直接使用原始 query 检索 |
| 子查询 JSON 解析失败 | 降级为直接使用原始 query 检索 |
| 子查询检索全部为空 | 使用原始 query 补充检索一次 |
| 回溯质量评估 LLM 失败 | 视为评分 0，直接进入第 2 轮 |
| 回溯联网搜索失败 | 使用第 1 轮本地结果 |
| 策略执行超时 | 降级为 direct 的 ReAct 流程 |

## 12. 非目标

- 不修改 direct 策略的现有流程
- 不创建新的 LangChain tool
- 不修改前端
- 不修改路由模块
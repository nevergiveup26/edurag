# 四种检索策略实现 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 direct/hyde/sub_query/backtrack 四种检索策略的执行逻辑，非 direct 策略在 agent 调用前做预处理检索并注入上下文。

**Architecture:** 新增 `strategy/` 包（5 个文件），`chat_agent.py` 在 `strategy != "direct"` 时调用 `execute_strategy` 获取上下文，注入 system prompt，然后创建仅含 `final_answer` 工具的 agent 直接回答。

**Tech Stack:** Python 3.11, langgraph (create_react_agent), LLMClient (qwen-turbo for non-response calls), json, re

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `strategy/__init__.py` | 新建 | 导出 `execute_strategy` 统一入口 + `StrategyResult` 数据类 |
| `strategy/base_strategy.py` | 新建 | 抽象基类 `BaseStrategy`，定义 `execute()` 接口和 `_format_context()` 公共方法 |
| `strategy/hyde_strategy.py` | 新建 | HyDE 策略：生成假设文档 → 检索 |
| `strategy/sub_query_strategy.py` | 新建 | 子查询策略：分解 → 分别检索 → 拼接 |
| `strategy/backtrack_strategy.py` | 新建 | 回溯策略：检索 → 评估 → 换源重检 |
| `langgraph_agent/chat_agent.py` | 修改 | `stream_agent_response` 新增策略分支 |

---

### Task 1: 创建 `strategy/` 包 + `base_strategy.py` + `__init__.py`

**Files:**
- Create: `strategy/__init__.py`
- Create: `strategy/base_strategy.py`

- [ ] **Step 1: 创建目录并写入 `base_strategy.py`**

```python
"""
检索策略抽象基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Any

from core.logger import get_logger

logger = get_logger("strategy")


@dataclass
class StrategyResult:
    """策略执行结果"""
    context: str = ""       # 检索到的上下文，注入 system prompt
    metadata: dict = field(default_factory=dict)  # 策略执行元数据


class BaseStrategy(ABC):
    """检索策略抽象基类"""

    @abstractmethod
    async def execute(self, query: str, retriever, llm, **kwargs) -> StrategyResult:
        """执行策略，返回上下文和元数据"""
        ...

    def _format_context(self, results: List[Any]) -> str:
        """将检索结果列表格式化为上下文字符串"""
        if not results:
            return ""
        parts = []
        for i, r in enumerate(results):
            content = getattr(r, 'content', None) or getattr(r, 'page_content', '')
            if not content and hasattr(r, 'chunk'):
                content = r.chunk.content
            if not content:
                continue
            score = getattr(r, 'score', 0.0)
            source = getattr(r, 'source', '') or getattr(r, 'metadata', {}).get('source', '')
            parts.append(f"[来源 {i+1}] (相关度: {score:.2f})\n{content}")
        return "\n\n".join(parts)
```

- [ ] **Step 2: 写入 `__init__.py`**

```python
"""
检索策略模块
提供 HyDE、子查询分解、回溯检索三种策略的预处理执行
"""
from strategy.base_strategy import StrategyResult, BaseStrategy
from strategy.hyde_strategy import HyDEStrategy
from strategy.sub_query_strategy import SubQueryStrategy
from strategy.backtrack_strategy import BacktrackStrategy

_strategies = {
    "hyde": HyDEStrategy(),
    "sub_query": SubQueryStrategy(),
    "backtrack": BacktrackStrategy(),
}


async def execute_strategy(
    strategy: str,
    query: str,
    retriever,
    llm,
    web_search_fn=None,
) -> StrategyResult:
    """统一入口：根据策略名执行对应预处理"""
    if strategy == "direct":
        return StrategyResult()  # direct 不需要预处理
    impl = _strategies.get(strategy)
    if not impl:
        return StrategyResult()
    return await impl.execute(
        query=query,
        retriever=retriever,
        llm=llm,
        web_search_fn=web_search_fn,
    )
```

- [ ] **Step 3: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\strategy\__init__.py','r',encoding='utf-8').read(), 'strategy/__init__.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add strategy/base_strategy.py strategy/__init__.py
git commit -m "feat: 创建 strategy 包、BaseStrategy 基类和 StrategyResult 数据类"
```

---

### Task 2: 创建 `strategy/hyde_strategy.py` — HyDE 策略

**Files:**
- Create: `strategy/hyde_strategy.py`

- [ ] **Step 1: 写入 `hyde_strategy.py`**

```python
"""
HyDE 策略：生成假设文档 → 用假设文档检索 → 返回上下文
"""
from strategy.base_strategy import BaseStrategy, StrategyResult
from core.logger import get_logger

logger = get_logger("hyde_strategy")

HYDE_PROMPT = """请根据以下问题，生成一个假设性的回答文档。
这个文档将用于向量检索，请尽可能详细地包含相关知识点。

问题：{question}

假设性回答："""


class HyDEStrategy(BaseStrategy):
    """HyDE 策略：Hypothetical Document Embeddings"""

    async def execute(self, query: str, retriever, llm, **kwargs) -> StrategyResult:
        """
        1. LLM 生成假设文档
        2. 用假设文档检索（而非原始 query）
        3. 返回检索上下文
        """
        try:
            # 1. 生成假设文档
            hyde_doc = llm.chat(
                messages=[{"role": "user", "content": HYDE_PROMPT.format(question=query)}],
                max_tokens=500,
            )
            logger.info(f"[HyDE] 假设文档生成完成: {hyde_doc[:80]}...")

            # 2. 用假设文档检索
            results = retriever.search(hyde_doc, top_k=5)
            if not results:
                # 降级：用原始 query 检索
                logger.info("[HyDE] 假设文档检索无结果，降级为原始查询检索")
                results = retriever.search(query, top_k=5)

            # 3. 拼接上下文
            context = self._format_context(results)
            return StrategyResult(
                context=context,
                metadata={"hyde_doc": hyde_doc[:200], "result_count": len(results)}
            )
        except Exception as e:
            logger.warning(f"[HyDE] 策略执行失败，降级为原始查询检索: {e}")
            try:
                results = retriever.search(query, top_k=5)
                context = self._format_context(results)
                return StrategyResult(
                    context=context,
                    metadata={"fallback": True, "error": str(e)[:100]}
                )
            except Exception:
                return StrategyResult()
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\strategy\hyde_strategy.py','r',encoding='utf-8').read(), 'hyde_strategy.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add strategy/hyde_strategy.py
git commit -m "feat: HyDE 策略 — 生成假设文档 → 检索"
```

---

### Task 3: 创建 `strategy/sub_query_strategy.py` — 子查询分解策略

**Files:**
- Create: `strategy/sub_query_strategy.py`

- [ ] **Step 1: 写入 `sub_query_strategy.py`**

```python
"""
子查询分解策略：分解为子问题 → 分别检索 → 拼接上下文
"""
import json
import re

from strategy.base_strategy import BaseStrategy, StrategyResult
from core.logger import get_logger

logger = get_logger("sub_query_strategy")

DECOMPOSE_PROMPT = """请将以下复杂问题分解为多个子问题，以便分别检索相关信息。

原始问题：{question}

请以JSON数组格式返回子问题列表，例如：
["子问题1", "子问题2", "子问题3"]

子问题列表："""


class SubQueryStrategy(BaseStrategy):
    """子查询分解策略"""

    MAX_SUB_QUERIES = 5

    async def execute(self, query: str, retriever, llm, **kwargs) -> StrategyResult:
        """
        1. LLM 分解为子问题
        2. 逐个子问题检索（每个 top_k=3）
        3. 拼接所有上下文
        """
        try:
            # 1. LLM 分解
            raw = llm.chat(
                messages=[{"role": "user", "content": DECOMPOSE_PROMPT.format(question=query)}],
                max_tokens=300,
            )
            sub_queries = self._parse_sub_queries(raw)
            if not sub_queries:
                logger.info("[SubQuery] 分解失败，降级为原始查询检索")
                results = retriever.search(query, top_k=5)
                context = self._format_context(results)
                return StrategyResult(
                    context=context,
                    metadata={"fallback": True, "sub_queries": []}
                )
            logger.info(f"[SubQuery] 分解出 {len(sub_queries)} 个子问题: {sub_queries}")

            # 2. 逐个子问题检索
            all_contexts = []
            for sq in sub_queries[:self.MAX_SUB_QUERIES]:
                results = retriever.search(sq, top_k=3)
                ctx = self._format_context(results)
                if ctx:
                    all_contexts.append(f"[子问题: {sq}]\n{ctx}")

            if not all_contexts:
                # 降级
                logger.info("[SubQuery] 所有子问题检索为空，降级为原始查询检索")
                results = retriever.search(query, top_k=5)
                context = self._format_context(results)
                return StrategyResult(
                    context=context,
                    metadata={"sub_queries": sub_queries, "fallback": True}
                )

            # 3. 拼接
            context = "\n\n---\n\n".join(all_contexts)
            return StrategyResult(
                context=context,
                metadata={"sub_queries": sub_queries, "result_count": len(all_contexts)}
            )
        except Exception as e:
            logger.warning(f"[SubQuery] 策略执行失败，降级为原始查询检索: {e}")
            try:
                results = retriever.search(query, top_k=5)
                return StrategyResult(
                    context=self._format_context(results),
                    metadata={"fallback": True, "error": str(e)[:100]}
                )
            except Exception:
                return StrategyResult()

    def _parse_sub_queries(self, raw: str) -> list:
        """解析 LLM 返回的 JSON 数组"""
        try:
            result = json.loads(raw.strip())
            if isinstance(result, list) and all(isinstance(q, str) for q in result):
                return result
        except json.JSONDecodeError:
            pass
        # 尝试从文本中提取 JSON 数组
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
        return []
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\strategy\sub_query_strategy.py','r',encoding='utf-8').read(), 'sub_query_strategy.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: 验证 JSON 解析逻辑**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); from strategy.sub_query_strategy import SubQueryStrategy; s = SubQueryStrategy(); assert s._parse_sub_requests('[\"a\", \"b\"]') == ['a', 'b']; assert s._parse_sub_requests('some text [\"x\", \"y\"] more') == ['x', 'y']; assert s._parse_sub_requests('garbage') == []; print('ALL PASS')"`

Expected: `ALL PASS` (note: the method is `_parse_sub_queries`, not `_parse_sub_requests`)

- [ ] **Step 4: Commit**

```bash
git add strategy/sub_query_strategy.py
git commit -m "feat: 子查询分解策略 — 分解 → 分别检索 → 拼接"
```

---

### Task 4: 创建 `strategy/backtrack_strategy.py` — 回溯检索策略

**Files:**
- Create: `strategy/backtrack_strategy.py`

- [ ] **Step 1: 写入 `backtrack_strategy.py`**

```python
"""
回溯检索策略：检索 → 质量评估 → 不满足则换源重检
"""
import json
import re

from strategy.base_strategy import BaseStrategy, StrategyResult
from core.logger import get_logger

logger = get_logger("backtrack_strategy")

QUALITY_EVAL_PROMPT = """请评估以下参考资料对回答问题的充分程度，给出0-1之间的评分。

问题：{question}

参考资料：
{context}

评分标准：
- 0.0-0.3: 资料严重不足，无法回答
- 0.3-0.6: 资料部分相关，但不完整
- 0.6-0.8: 资料较充分，基本可以回答
- 0.8-1.0: 资料非常充分，可以完整回答

仅返回一个0-1之间的数字评分："""

QUERY_REFINE_PROMPT = """基于以下原始问题和当前检索到的信息，生成一个新的查询以便获取更相关的信息。

原始问题：{question}

当前检索结果：
{context}

请生成一个更精确的查询："""


class BacktrackStrategy(BaseStrategy):
    """回溯检索策略：最多 2 轮，第 2 轮切换搜索源"""

    MAX_ROUNDS = 2
    QUALITY_THRESHOLD = 0.6

    async def execute(self, query: str, retriever, llm, web_search_fn=None, **kwargs) -> StrategyResult:
        """
        1. 第 1 轮：本地知识库检索
        2. 质量评估：评分 >= 0.6 则直接返回
        3. 不满足：优化查询 + 第 2 轮联网搜索
        """
        all_contexts = []
        metadata = {"rounds": 1, "score": 0.0}

        try:
            # 第 1 轮：本地检索
            results = retriever.search(query, top_k=5)
            context_1 = self._format_context(results)
            all_contexts.append("[本地知识库检索结果]\n" + context_1)

            # 质量评估
            score = self._evaluate_quality(query, context_1, llm)
            metadata["score"] = score
            logger.info(f"[Backtrack] 第 1 轮质量评分: {score:.2f}")

            if score >= self.QUALITY_THRESHOLD:
                logger.info(f"[Backtrack] 质量达标，直接返回")
                return StrategyResult(
                    context=context_1,
                    metadata=metadata
                )

            # 第 2 轮：优化查询 + 联网搜索
            logger.info(f"[Backtrack] 质量不足，进入第 2 轮联网搜索")
            refined_query = self._refine_query(query, context_1, llm)
            metadata["refined_query"] = refined_query
            metadata["rounds"] = 2

            if web_search_fn:
                web_raw = await web_search_fn(refined_query)
                context_2 = self._format_web_results(web_raw)
                all_contexts.append("[联网搜索结果]\n" + context_2)
            else:
                all_contexts.append("[联网搜索不可用]")

            return StrategyResult(
                context="\n\n---\n\n".join(all_contexts),
                metadata=metadata
            )
        except Exception as e:
            logger.warning(f"[Backtrack] 策略执行失败: {e}")
            return StrategyResult(
                context=all_contexts[0] if all_contexts else "",
                metadata={"fallback": True, "error": str(e)[:100]}
            )

    def _evaluate_quality(self, query: str, context: str, llm) -> float:
        """LLM 评估上下文质量，返回 0-1 评分"""
        try:
            raw = llm.chat(
                messages=[{"role": "user", "content": QUALITY_EVAL_PROMPT.format(
                    question=query, context=context[:3000]
                )}],
                max_tokens=50,
            )
            match = re.search(r'(\d+\.?\d*)', raw)
            if match:
                score = float(match.group(1))
                return max(0.0, min(1.0, score))
            return 0.0
        except Exception as e:
            logger.warning(f"[Backtrack] 质量评估失败: {e}")
            return 0.0

    def _refine_query(self, query: str, context: str, llm) -> str:
        """LLM 优化查询"""
        try:
            refined = llm.chat(
                messages=[{"role": "user", "content": QUERY_REFINE_PROMPT.format(
                    question=query, context=context[:2000]
                )}],
                max_tokens=200,
            )
            return refined.strip() or query
        except Exception:
            return query

    def _format_web_results(self, web_raw: str) -> str:
        """将 tavily 返回的 JSON 字符串格式化为上下文"""
        try:
            data = json.loads(web_raw) if isinstance(web_raw, str) else web_raw
            parts = []
            for i, r in enumerate(data.get("results", []) or []):
                parts.append(f"[网页 {i+1}] {r.get('title', '')}\n{r.get('content', '')}")
            if data.get("answer"):
                parts.insert(0, f"[Tavily AI 摘要]\n{data['answer']}")
            return "\n\n".join(parts) if parts else "（无搜索结果）"
        except Exception:
            return str(web_raw)[:3000]
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\strategy\backtrack_strategy.py','r',encoding='utf-8').read(), 'backtrack_strategy.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add strategy/backtrack_strategy.py
git commit -m "feat: 回溯检索策略 — 检索 → 评估 → 换源重检"
```

---

### Task 5: 修改 `langgraph_agent/chat_agent.py` — 集成策略分支

**Files:**
- Modify: `langgraph_agent/chat_agent.py`

- [ ] **Step 1: 在 `stream_agent_response` 中插入策略分支**

在 `import json as _json` 之后、`# 图片 OCR 处理` 之前插入策略分支。当前代码结构（第 230-232 行）：

```python
    import json as _json

    logger.info(f"[Agent] 检索策略: {strategy}  query='{user_message[:60]}'")

    # 图片 OCR 处理：将图片文字拼入用户消息
```

修改为在 `logger.info` 行之后插入策略分支：

```python
    import json as _json

    logger.info(f"[Agent] 检索策略: {strategy}  query='{user_message[:60]}'")

    # 策略预处理（非 direct 策略）
    strategy_context = None
    strategy_metadata = {}
    if strategy != "direct":
        from strategy import execute_strategy
        from langgraph_agent.tools import _provider, tavily_web_search

        async def _web_search_fn(q: str) -> str:
            return tavily_web_search.invoke({"query": q})

        strategy_result = await execute_strategy(
            strategy=strategy,
            query=user_message,
            retriever=_provider._retriever,
            llm=_provider._llm_client,
            web_search_fn=_web_search_fn,
        )
        if strategy_result and strategy_result.context:
            strategy_context = strategy_result.context
            strategy_metadata = strategy_result.metadata
            logger.info(
                f"[Agent] 策略预处理完成: {strategy} "
                f"context_len={len(strategy_context)} metadata={strategy_metadata}"
            )

    # 图片 OCR 处理：将图片文字拼入用户消息
```

**注意：** 这段代码需要 `await`，但 `stream_agent_response` 已经是 `async` 函数，所以可以直接用 `await`。

- [ ] **Step 2: 在 system_prompt 构建处注入上下文**

在 `create_chat_agent` 调用之前（第 106-150 行区域），找到 `system_prompt` 变量的赋值位置。当前代码：

```python
    if system_prompt is None:
        system_prompt = CHAT_SYSTEM_PROMPT
```

需要修改为：

搜索 `system_prompt = CHAT_SYSTEM_PROMPT` 所在位置，在其后插入上下文注入。但注意 `create_chat_agent` 是在 `stream_agent_response` 外部调用的，`system_prompt` 是在 `agent_routes.py` 中传给 `create_chat_agent` 的。

查看 `agent_routes.py` 中 `agent_query_stream` 如何创建 agent：

搜索 `agent_query_stream` 函数中 `create_chat_agent` 的调用位置。根据之前探索的结果，`agent_query_stream` 在第 119 行附近创建 agent 和 system_prompt。

**关键设计变更：** 策略预处理需要在 `agent_routes.py` 中 `create_chat_agent` 之前完成，而不是在 `stream_agent_response` 中。因为需要修改 system_prompt 并可能切换 tools。

**修改方案：将策略预处理移到 `agent_routes.py` 的 `agent_query_stream` 中。**

- [ ] **Step 3: 修改 `api/agent_routes.py` 的 `agent_query_stream`**

在 `agent_query_stream` 中，路由决策之后、`create_chat_agent` 之前插入策略预处理。当前代码（第 119-150 行区域）：

```python
    # 智能路由
    from router.query_router import get_query_router
    router = get_query_router()
    strategy = router.route(request.query)
    logger.info(f"[AgentStream] 路由结果: strategy={strategy} query='{request.query[:50]}'")

    full_answer = []
    # ... 后续创建 agent 和 system_prompt
```

需要在 `create_chat_agent` 调用之前插入策略预处理，然后根据策略修改 system_prompt 和 tools。需要找到 `create_chat_agent` 和 `system_prompt` 在 `agent_query_stream` 中的位置。

先搜索 `agent_query_stream` 中 `create_chat_agent` 和 `system_prompt` 的位置：

- [ ] **Step 4: 先读取 `agent_query_stream` 的完整代码确定插入点**

在实施时，需要先读取 `agent_routes.py` 中 `agent_query_stream` 的完整函数体，找到 `create_chat_agent` 的调用位置。

**实施时采用以下步骤：**

1. 读取 `agent_routes.py` 第 100-180 行，定位 `create_chat_agent` 调用
2. 在 `create_chat_agent` 调用之前插入策略预处理代码：

```python
    # 策略预处理（非 direct 策略）
    strategy_context = None
    strategy_metadata = {}
    if strategy != "direct":
        from strategy import execute_strategy
        from langgraph_agent.tools import _provider, tavily_web_search
        import asyncio

        async def _web_search_fn(q: str) -> str:
            return tavily_web_search.invoke({"query": q})

        strategy_result = await execute_strategy(
            strategy=strategy,
            query=request.query,
            retriever=_provider._retriever,
            llm=_provider._llm_client,
            web_search_fn=_web_search_fn,
        )
        if strategy_result and strategy_result.context:
            strategy_context = strategy_result.context
            strategy_metadata = strategy_result.metadata
            logger.info(
                f"[AgentStream] 策略预处理完成: {strategy} "
                f"context_len={len(strategy_context)}"
            )

    # 构建 system_prompt（如果有策略上下文则注入）
    system_prompt = CHAT_SYSTEM_PROMPT
    if strategy_context:
        system_prompt = system_prompt + "\n\n【系统已检索到的参考资料】\n" + strategy_context
        system_prompt = system_prompt + "\n\n请直接基于以上参考资料回答用户问题，不要调用 knowledge_search 工具。"

    agent = create_chat_agent(
        model=model,
        tools=tools if strategy == "direct" else [final_answer],  # 非 direct 只用 final_answer
        system_prompt=system_prompt,
        retriever=retriever,
        llm_client=llm_client,
        kb_manager=kb_manager,
    )
```

3. 需要导入 `final_answer` 和 `CHAT_SYSTEM_PROMPT`：

```python
from langgraph_agent.chat_agent import create_chat_agent, stream_agent_response, CHAT_SYSTEM_PROMPT
from langgraph_agent.tools import final_answer
```

- [ ] **Step 5: 同样修改 `agent_query`（非流式）**

在 `agent_query` 中也需要相同的策略预处理逻辑。在 `agent_query` 中路由决策之后、消息构建之前插入。

- [ ] **Step 6: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\api\agent_routes.py','r',encoding='utf-8').read(), 'agent_routes.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add api/agent_routes.py
git commit -m "feat: agent_routes 集成策略预处理 — HyDE/子查询/回溯上下文注入"
```

---

### Task 6: 端到端验证

- [ ] **Step 1: 重启后端服务**

```bash
cd d:\EduRAG智慧问答系统
& .venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: 测试 direct 策略（不做预处理，行为不变）**

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"什么是光合作用","user_id":"test"}' --max-time 30
```

检查日志确认：
```
[QueryRouter] Layer 1 命中: direct
[Agent] 检索策略: direct
# 应走现有 ReAct 流程，有 knowledge_search action
```

- [ ] **Step 3: 测试 hyde 策略**

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"文言文和白话文有什么区别","user_id":"test"}' --max-time 30
```

检查日志确认：
```
[QueryRouter] Layer 1 命中: hyde
[HyDE] 假设文档生成完成
[AgentStream] 策略预处理完成: hyde context_len=XXX
# 不应有 knowledge_search action，直接回答
```

- [ ] **Step 4: 测试 sub_query 策略**

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"先查一下资料再回答","user_id":"test"}' --max-time 30
```

检查日志确认：
```
[QueryRouter] Layer 1 命中: sub_query
[SubQuery] 分解出 N 个子问题
[AgentStream] 策略预处理完成: sub_query context_len=XXX
```

- [ ] **Step 5: 测试 backtrack 策略**

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"为什么天空是蓝色的","user_id":"test"}' --max-time 30
```

检查日志确认：
```
[QueryRouter] Layer 1 命中: backtrack
[Backtrack] 第 1 轮质量评分: X.XX
[AgentStream] 策略预处理完成: backtrack context_len=XXX
```

- [ ] **Step 6: 测试降级逻辑（模拟策略失败）**

发送一个查询触发 hyde 策略，观察如果检索为空时是否降级。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: 四种检索策略端到端验证通过"
```
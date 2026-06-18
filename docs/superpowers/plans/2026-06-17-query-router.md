# 智能查询路由 — 三层架构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 chat 模式下，根据用户查询复杂度自动选择最优检索策略（direct/hyde/sub_query/backtrack），通过规则→相似度→LLM 三层递进路由实现精准分发。

**Architecture:** 新增 `router/` 包，包含 5 个文件。`QueryRouter` 作为统一入口，串联 3 层路由。`agent_routes.py` 在调用 `stream_agent_response` 之前插入路由决策，`chat_agent.py` 新增 `strategy` 参数。

**Tech Stack:** Python 3.11, re (正则), Vectorizer (text-embedding-v4), LLMClient (qwen-turbo), numpy

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `router/__init__.py` | 新建 | 导出 `get_query_router` 单例工厂 |
| `router/rule_router.py` | 新建 | Layer 1: 关键词+正则规则匹配 |
| `router/similarity_router.py` | 新建 | Layer 2: 向量相似度+锚点示例库 |
| `router/llm_router.py` | 新建 | Layer 3: qwen-turbo 意图分类 |
| `router/query_router.py` | 新建 | 三层串联编排，LRU 缓存和降级 |
| `api/agent_routes.py` | 修改 | 调用 `QueryRouter.route()`，传入 `stream_agent_response` |
| `langgraph_agent/chat_agent.py` | 修改 | `stream_agent_response` 新增 `strategy` 参数 |

---

### Task 1: 创建 `router/` 包和 `__init__.py`

**Files:**
- Create: `router/__init__.py`

- [ ] **Step 1: 创建目录并写入 `__init__.py`**

```python
"""
智能查询路由模块
提供三层递进路由：规则(rule) → 相似度(similarity) → LLM(llm)
"""
from router.query_router import QueryRouter, get_query_router

__all__ = ["QueryRouter", "get_query_router"]
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add router/__init__.py
git commit -m "feat: 创建 router 包和 __init__.py"
```

---

### Task 2: 创建 `router/rule_router.py` — Layer 1 规则路由

**Files:**
- Create: `router/rule_router.py`

- [ ] **Step 1: 写入 `rule_router.py`**

```python
"""
Layer 1: 规则路由
基于关键词+正则匹配，零延迟、零成本
预期命中率 ~60%
"""
import re
from typing import Optional


class RuleRouter:
    """规则路由：关键词+正则匹配，按优先级依次匹配"""

    # 格式: (正则模式, 最大长度限制(0=不限制), 策略名)
    RULES = [
        # 短事实查询 → direct
        (r"(是谁|什么是|什么叫|定义|公式|多少|哪个|哪里|哪年|谁)", 15, "direct"),
        # 对比分析 → hyde
        (r"(区别|对比|比较|哪个更好|vs|有什么不同)", 0, "hyde"),
        # 多步推理 → sub_query
        (r"(先.*再|然后|步骤|怎么做|怎么解|如何|规划|设计)", 0, "sub_query"),
        # 深度研究 → backtrack
        (r"(为什么|原因|原理|证明|推导|怎么来的)", 0, "backtrack"),
    ]

    def route(self, query: str) -> Optional[str]:
        """
        按优先级依次匹配规则，返回第一个命中的策略名。
        未命中返回 None，交给 Layer 2。

        Args:
            query: 用户查询文本

        Returns:
            策略名（direct/hyde/sub_query/backtrack）或 None
        """
        q = query.strip()
        for pattern, max_len, strategy in self.RULES:
            if max_len > 0 and len(q) > max_len:
                continue
            if re.search(pattern, q):
                return strategy
        return None
```

- [ ] **Step 2: 验证语法和基础逻辑**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); from router.rule_router import RuleRouter; r = RuleRouter(); tests = [('什么是光合作用', 'direct'), ('内燃机和电动机的区别', 'hyde'), ('先查一下资料再回答', 'sub_query'), ('为什么天是蓝色的', 'backtrack'), ('你好', None)]; all(r.route(q) == e for q, e in tests) and print('ALL PASS')"`

Expected: `ALL PASS`

- [ ] **Step 3: Commit**

```bash
git add router/rule_router.py
git commit -m "feat: Layer 1 规则路由 — 关键词+正则匹配"
```

---

### Task 3: 创建 `router/similarity_router.py` — Layer 2 相似度路由

**Files:**
- Create: `router/similarity_router.py`

- [ ] **Step 1: 写入 `similarity_router.py`**

```python
"""
Layer 2: 相似度路由
基于向量相似度匹配预设锚点示例库
预期命中率 ~30%（累计 90%），延迟 ~50ms
"""
import numpy as np
from typing import Optional, List, Tuple

from core.logger import get_logger

logger = get_logger("similarity_router")

# 锚点示例库：每种策略 5 条典型查询
ANCHOR_EXAMPLES = {
    "direct": [
        "什么是光合作用",
        "牛顿第一定律的内容",
        "中国的首都是哪里",
        "圆的面积公式是什么",
        "抗日战争是哪一年开始的",
    ],
    "hyde": [
        "内燃机和电动机的优缺点对比",
        "文言文和白话文有什么区别",
        "线上教育和线下教育哪个更好",
        "古典音乐和流行音乐的比较",
        "民主制度和专制制度的区别",
    ],
    "sub_query": [
        "先查一下秦始皇统一六国的过程，再分析对后世的影响",
        "帮我分析这道二次函数的题怎么做",
        "如何写一篇关于环保的议论文，分几个步骤",
        "设计一个科学实验验证光合作用需要光",
        "怎么规划一个月的期末复习计划",
    ],
    "backtrack": [
        "为什么天空是蓝色的，背后的物理原理是什么",
        "黑洞的形成原因和霍金辐射的推导过程",
        "达尔文进化论的证据和论证逻辑",
        "为什么说熵增定律是宇宙的终极规律",
        "量子纠缠的原理是什么，为什么爱因斯坦说它是鬼魅般的超距作用",
    ],
}


class SimilarityRouter:
    """相似度路由：锚点向量化后做余弦相似度匹配"""

    def __init__(self, similarity_threshold: float = 0.75):
        """
        Args:
            similarity_threshold: 相似度阈值，低于此值返回 None
        """
        self.threshold = similarity_threshold
        self._anchor_vectors: Optional[np.ndarray] = None  # shape: (20, 1024)
        self._anchor_labels: List[str] = []  # 每条锚点对应的策略名
        self._initialized = False

    def _ensure_initialized(self):
        """延迟初始化：将锚点向量化（避免 import 时依赖 Vectorizer）"""
        if self._initialized:
            return
        from data_processor.vectorizer import Vectorizer
        vectorizer = Vectorizer()
        all_texts = []
        self._anchor_labels = []
        for strategy, examples in ANCHOR_EXAMPLES.items():
            for text in examples:
                all_texts.append(text)
                self._anchor_labels.append(strategy)
        vectors = vectorizer.embed(all_texts)
        self._anchor_vectors = np.array(vectors, dtype=np.float32)
        self._initialized = True
        logger.info(f"[SimilarityRouter] 锚点库初始化完成，共 {len(all_texts)} 条")

    def route(self, query: str) -> Optional[str]:
        """
        将查询向量化后与锚点库做余弦相似度匹配。
        取 top-1，相似度 >= threshold 则返回策略名，否则返回 None。

        Args:
            query: 用户查询文本

        Returns:
            策略名或 None
        """
        try:
            self._ensure_initialized()
            from data_processor.vectorizer import Vectorizer
            vectorizer = Vectorizer()
            query_vec = np.array(vectorizer.embed_query(query), dtype=np.float32)

            # 计算余弦相似度
            query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
            anchor_norms = self._anchor_vectors / (
                np.linalg.norm(self._anchor_vectors, axis=1, keepdims=True) + 1e-8
            )
            similarities = np.dot(anchor_norms, query_norm)

            best_idx = int(np.argmax(similarities))
            best_score = float(similarities[best_idx])

            if best_score >= self.threshold:
                strategy = self._anchor_labels[best_idx]
                logger.debug(
                    f"[SimilarityRouter] 命中: strategy={strategy} "
                    f"score={best_score:.3f} anchor='{ANCHOR_EXAMPLES[strategy][best_idx % 5]}'"
                )
                return strategy

            logger.debug(f"[SimilarityRouter] 未命中: best_score={best_score:.3f} < {self.threshold}")
            return None
        except Exception as e:
            logger.warning(f"[SimilarityRouter] 异常，跳过 Layer 2: {e}")
            return None
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\router\similarity_router.py','r',encoding='utf-8').read(), 'similarity_router.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add router/similarity_router.py
git commit -m "feat: Layer 2 相似度路由 — 锚点向量+余弦相似度匹配"
```

---

### Task 4: 创建 `router/llm_router.py` — Layer 3 LLM 路由

**Files:**
- Create: `router/llm_router.py`

- [ ] **Step 1: 写入 `llm_router.py`**

```python
"""
Layer 3: LLM 路由
使用 qwen-turbo 做意图分类，兜底保障
延迟 ~300-500ms，含 LRU 缓存
"""
import json
import re
from typing import Optional
from collections import OrderedDict

from core.logger import get_logger

logger = get_logger("llm_router")

CLASSIFICATION_PROMPT = """你是一个查询分类器。请将以下用户查询分类到 4 种检索策略之一：

- direct：简单事实查询，直接检索即可回答（如"什么是XX"、"XX的定义"、"XX的公式"）
- hyde：对比分析类问题，需要生成假设文档辅助检索（如"XX和YY的区别"、"XX和YY哪个更好"）
- sub_query：多步推理或复合问题，需要分解为子问题（如"先查XX再分析YY"、"如何做XX"）
- backtrack：深层原理类问题，需要多轮检索和验证（如"为什么XX"、"XX的原理"、"证明XX"）

用户查询：{query}

请仅返回 JSON，不要包含任何其他文字：
{{"strategy": "策略名", "confidence": 0.0~1.0}}"""


class LLMRouter:
    """LLM 路由：qwen-turbo 意图分类，含 LRU 缓存"""

    MAX_CACHE_SIZE = 500

    def __init__(self):
        self._llm = None  # 延迟初始化
        self._cache: OrderedDict[str, str] = OrderedDict()

    def _get_llm(self):
        """延迟获取 fast_llm（避免 import 时初始化）"""
        if self._llm is None:
            from llm.llm_client import get_fast_llm
            self._llm = get_fast_llm()
        return self._llm

    def _cache_get(self, query: str) -> Optional[str]:
        return self._cache.get(query)

    def _cache_set(self, query: str, strategy: str):
        if len(self._cache) >= self.MAX_CACHE_SIZE:
            self._cache.popitem(last=False)  # LRU: 删除最旧的
        self._cache[query] = strategy

    def route(self, query: str) -> str:
        """
        LLM 意图分类，必定返回策略名。
        失败或置信度低时降级为 direct。

        Args:
            query: 用户查询文本

        Returns:
            策略名（direct/hyde/sub_query/backtrack）
        """
        # 1. 查 LRU 缓存
        cached = self._cache_get(query)
        if cached:
            logger.debug(f"[LLMRouter] 缓存命中: {cached}")
            return cached

        try:
            llm = self._get_llm()
            prompt = CLASSIFICATION_PROMPT.format(query=query)
            response = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )

            # 解析 JSON
            result = self._parse_response(response)
            strategy = result.get("strategy", "direct")
            confidence = result.get("confidence", 0.0)

            # 验证策略名有效性
            valid_strategies = {"direct", "hyde", "sub_query", "backtrack"}
            if strategy not in valid_strategies:
                logger.warning(f"[LLMRouter] 无效策略 '{strategy}'，降级为 direct")
                strategy = "direct"

            # 置信度检查
            if confidence < 0.5:
                logger.info(f"[LLMRouter] 置信度过低 {confidence:.2f}，降级为 direct")
                strategy = "direct"

            self._cache_set(query, strategy)
            logger.info(f"[LLMRouter] 分类结果: {strategy} (confidence={confidence:.2f})")
            return strategy

        except Exception as e:
            logger.warning(f"[LLMRouter] 分类失败，降级为 direct: {e}")
            self._cache_set(query, "direct")
            return "direct"

    def _parse_response(self, response: str) -> dict:
        """从 LLM 响应中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            pass

        # 尝试从代码块中提取
        match = re.search(r'\{[^{}]*"strategy"[^{}]*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"[LLMRouter] 无法解析响应: {response[:200]}")
        return {}
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\router\llm_router.py','r',encoding='utf-8').read(), 'llm_router.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: 验证 JSON 解析逻辑**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); from router.llm_router import LLMRouter; r = LLMRouter(); assert r._parse_response('{\"strategy\": \"direct\", \"confidence\": 0.9}') == {'strategy': 'direct', 'confidence': 0.9}; assert r._parse_response('some text {\"strategy\": \"hyde\", \"confidence\": 0.7} more') == {'strategy': 'hyde', 'confidence': 0.7}; assert r._parse_response('garbage') == {}; print('ALL PASS')"`

Expected: `ALL PASS`

- [ ] **Step 4: Commit**

```bash
git add router/llm_router.py
git commit -m "feat: Layer 3 LLM 路由 — qwen-turbo 意图分类+LRU 缓存"
```

---

### Task 5: 创建 `router/query_router.py` — 统一入口

**Files:**
- Create: `router/query_router.py`

- [ ] **Step 1: 写入 `query_router.py`**

```python
"""
智能查询路由 — 统一入口
三层递进：RuleRouter → SimilarityRouter → LLMRouter
含 LRU 全链路缓存和降级逻辑
"""
from typing import Optional
from collections import OrderedDict

from core.logger import get_logger
from router.rule_router import RuleRouter
from router.similarity_router import SimilarityRouter
from router.llm_router import LLMRouter

logger = get_logger("query_router")

# 全局单例
_query_router: Optional["QueryRouter"] = None


class QueryRouter:
    """三层递进查询路由，含全链路 LRU 缓存"""

    MAX_CACHE_SIZE = 500

    def __init__(self):
        self.rule_router = RuleRouter()
        self.similarity_router = SimilarityRouter(similarity_threshold=0.75)
        self.llm_router = LLMRouter()
        self._cache: OrderedDict[str, str] = OrderedDict()

    def _cache_get(self, query: str) -> Optional[str]:
        return self._cache.get(query)

    def _cache_set(self, query: str, strategy: str):
        if len(self._cache) >= self.MAX_CACHE_SIZE:
            self._cache.popitem(last=False)
        self._cache[query] = strategy

    def route(self, query: str) -> str:
        """
        三层递进路由，返回策略名。

        流程:
        1. 查全链路缓存
        2. Layer 1: 规则匹配（0ms）
        3. Layer 2: 相似度匹配（~50ms）
        4. Layer 3: LLM 分类（~300-500ms，兜底）

        Args:
            query: 用户查询文本

        Returns:
            策略名（direct/hyde/sub_query/backtrack）
        """
        # 1. 全链路缓存
        cached = self._cache_get(query)
        if cached:
            logger.debug(f"[QueryRouter] 缓存命中: {cached}")
            return cached

        # 2. Layer 1: 规则
        result = self.rule_router.route(query)
        if result:
            logger.info(f"[QueryRouter] Layer 1 命中: {result}  query='{query[:50]}'")
            self._cache_set(query, result)
            return result

        # 3. Layer 2: 相似度
        result = self.similarity_router.route(query)
        if result:
            logger.info(f"[QueryRouter] Layer 2 命中: {result}  query='{query[:50]}'")
            self._cache_set(query, result)
            return result

        # 4. Layer 3: LLM 兜底
        result = self.llm_router.route(query)
        logger.info(f"[QueryRouter] Layer 3 兜底: {result}  query='{query[:50]}'")
        self._cache_set(query, result)
        return result


def get_query_router() -> QueryRouter:
    """获取 QueryRouter 全局单例"""
    global _query_router
    if _query_router is None:
        _query_router = QueryRouter()
    return _query_router
```

- [ ] **Step 2: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\router\query_router.py','r',encoding='utf-8').read(), 'query_router.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: 验证 RuleRouter 集成（不依赖 embedding API）**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); from router.query_router import QueryRouter; r = QueryRouter(); assert r.route('什么是光合作用') == 'direct'; assert r.route('内燃机和电动机的区别') == 'hyde'; assert r.route('先查一下再回答') == 'sub_query'; assert r.route('为什么天是蓝色的') == 'backtrack'; print('ALL PASS')"`

Expected: `ALL PASS`

- [ ] **Step 4: Commit**

```bash
git add router/query_router.py
git commit -m "feat: QueryRouter 统一入口 — 三层递进+LRU 缓存"
```

---

### Task 6: 修改 `api/agent_routes.py` — 集成路由

**Files:**
- Modify: `api/agent_routes.py`

- [ ] **Step 1: 在 `agent_query` 中集成路由**

修改 `agent_query` 函数（第 41-47 行），在构建消息时使用路由策略：

```python
# 在 agent_query 函数中，第 41 行之后（agent_messages 构建之前），修改为：
    query_text = request.query
    # 智能路由：确定检索策略
    from router.query_router import get_query_router
    router = get_query_router()
    strategy = router.route(query_text)
    logger.info(f"[AgentQuery] 路由结果: strategy={strategy} query='{query_text[:50]}'")

    # 图片 OCR 处理
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

    agent_messages = []
    for h in history[-20:]:
        if h.get("role") == "user":
            agent_messages.append(HumanMessage(content=h.get("content", "")))
        elif h.get("role") == "assistant":
            agent_messages.append(AIMessage(content=h.get("content", "")))
    agent_messages.append(HumanMessage(content=query_text))
```

注意：`agent_query` 当前第 41-47 行已有 OCR 处理逻辑（来自之前的 images 功能），需要确认路由代码插入在 OCR 之前。当前代码结构为：

```python
    # 第 41 行附近
    agent_messages = []
    for h in history[-20:]:
        if h.get("role") == "user":
            agent_messages.append(HumanMessage(content=h.get("content", "")))
        elif h.get("role") == "assistant":
            agent_messages.append(AIMessage(content=h.get("content", "")))
    query_text = request.query
    if request.images:
        ...
    agent_messages.append(HumanMessage(content=query_text))
```

修改为在 `query_text = request.query` 之后立即插入路由：

```python
    query_text = request.query
    # 智能路由
    from router.query_router import get_query_router
    router = get_query_router()
    strategy = router.route(query_text)
```

- [ ] **Step 2: 在 `agent_query_stream` 中集成路由**

修改 `agent_query_stream` 函数（第 131-133 行），在 `stream_agent_response` 调用前插入路由，并传递 `strategy` 参数：

```python
# 在 agent_query_stream 函数中，第 119 行（system_prompt 构建之后）插入：
    # 智能路由
    from router.query_router import get_query_router
    router = get_query_router()
    strategy = router.route(request.query)
    logger.info(f"[AgentStream] 路由结果: strategy={strategy} query='{request.query[:50]}'")

# 修改第 131-133 行的 stream_agent_response 调用：
            async for sse_str in stream_agent_response(
                agent, request.query, config=config, history=history,
                conversation_id=conversation_id, user_id=request.user_id,
                images=request.images,
                strategy=strategy,
            ):
```

- [ ] **Step 3: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\api\agent_routes.py','r',encoding='utf-8').read(), 'agent_routes.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/agent_routes.py
git commit -m "feat: agent_routes 集成 QueryRouter 三层路由"
```

---

### Task 7: 修改 `langgraph_agent/chat_agent.py` — 新增 strategy 参数

**Files:**
- Modify: `langgraph_agent/chat_agent.py`

- [ ] **Step 1: 修改 `stream_agent_response` 函数签名**

在 `images` 参数后新增 `strategy` 参数：

```python
async def stream_agent_response(
    agent: CompiledStateGraph,
    user_message: str,
    config: RunnableConfig = None,
    history: List[dict] = None,
    conversation_id: str = None,
    user_id: str = None,
    images: Optional[List[str]] = None,
    strategy: str = "direct",
) -> AsyncGenerator[str, None]:
```

- [ ] **Step 2: 在 LangFuse trace 中记录策略**

在 `start_trace` 调用（第 232-238 行）的 metadata 中增加策略信息。当前代码：

```python
        trace = start_trace(
            query=user_message,
            conversation_id=conversation_id,
            user_id=user_id,
            strategy="langgraph_agent",
        )
```

修改为使用实际路由策略（注意：`start_trace` 的参数名是 `strategy`，但实际含义是追踪策略类型，这里保持 `langgraph_agent` 不变，在 metadata 中额外记录检索策略）：

当前 `start_trace` 调用在第 232-238 行，在调用后添加日志：

```python
        logger.info(f"[Agent] 检索策略: {strategy}  query='{user_message[:60]}'")
```

在 done 事件的 metadata 中增加策略信息（在 `trace.update` 调用处，第 363-372 行）：

```python
            trace.update(
                output=answer,
                status="success",
                metadata={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "retrieval_strategy": strategy,  # 新增
                },
            )
```

- [ ] **Step 3: 语法验证**

Run: `& 'd:\EduRAG智慧问答系统\.venv\Scripts\python.exe' -c "import sys; sys.path.insert(0, r'd:\EduRAG智慧问答系统'); compile(open(r'd:\EduRAG智慧问答系统\langgraph_agent\chat_agent.py','r',encoding='utf-8').read(), 'chat_agent.py', 'exec'); print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add langgraph_agent/chat_agent.py
git commit -m "feat: stream_agent_response 新增 strategy 参数，记录到 LangFuse"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 重启后端服务**

```bash
cd d:\EduRAG智慧问答系统
& .venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: 测试 RuleRouter 规则匹配**

```bash
# 测试 direct（短事实查询）
curl -X POST http://localhost:8000/api/v1/student/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是光合作用", "user_id": "test"}'

# 测试 hyde（对比分析）
curl -X POST http://localhost:8000/api/v1/student/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "文言文和白话文有什么区别", "user_id": "test"}'

# 测试 sub_query（多步推理）
curl -X POST http://localhost:8000/api/v1/student/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "先查一下资料再分析", "user_id": "test"}'

# 测试 backtrack（深度研究）
curl -X POST http://localhost:8000/api/v1/student/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "为什么天空是蓝色的", "user_id": "test"}'
```

- [ ] **Step 3: 查看日志确认路由**

观察后端日志，确认输出类似的日志行：
```
[QueryRouter] Layer 1 命中: direct  query='什么是光合作用'
[QueryRouter] Layer 1 命中: hyde  query='文言文和白话文有什么区别'
[QueryRouter] Layer 1 命中: sub_query  query='先查一下资料再分析'
[QueryRouter] Layer 1 命中: backtrack  query='为什么天空是蓝色的'
```

- [ ] **Step 4: 测试非规则命中查询（触发 Layer 2 或 Layer 3）**

```bash
# 模糊查询，可能走 Layer 2 或 Layer 3
curl -X POST http://localhost:8000/api/v1/student/agent/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "请帮我解答这道数学题", "user_id": "test"}'
```

- [ ] **Step 5: 验证缓存机制**

发送两次相同的查询，第二次应看到 `[QueryRouter] 缓存命中` 日志。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: 智能查询路由三层架构完成，端到端验证通过"
```
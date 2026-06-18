# 统一评估器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 合并 `evaluator.py` 和 `ragas_evaluator.py` 为统一评估器，去掉 ragas 库依赖，混合模式实现 LLM 评判指标

**Architecture:** 新建 `metrics/` 子包（retrieval/generation/llm_judge），新建 `unified_evaluator.py` 主入口（同步+流式双入口），新建 `report.py` 生成 HTML 报告。保留 `evaluator.py` 为兼容包装，删除 `ragas_evaluator.py`，更新 `admin_routes.py` API 端点

**Tech Stack:** Python 3.10+, jieba (分词), numpy (向量计算), matplotlib (图表), 项目已有 LLMClient/Vectorizer/HybridRetriever

---

## 文件结构

```
evaluation/
├── metrics/                    ← 新建子包
│   ├── __init__.py             ← 导出所有指标函数
│   ├── retrieval.py            ← 检索指标 + embedding 精度/相关性
│   ├── generation.py           ← BLEU/ROUGE/关键词（从 evaluator.py 迁移）
│   └── llm_judge.py            ← Faithfulness(分解) + AnswerRelevancy + Correctness
├── unified_evaluator.py        ← 新建：统一评估器主入口
├── report.py                   ← 新建：HTML 报告生成
├── evaluator.py                ← 修改：标记废弃，转调 unified_evaluator
├── ragas_evaluator.py          ← 删除
├── ablation.py                 ← 修改：query_func 返回值适配
├── run_retrieval_eval.py       ← 不变
├── build_k12_test_set.py       ← 不变
├── cmrc_evaluator.py           ← 不变
└── cmrc2018_evaluate.py        ← 不变
```

---

### Task 1: 创建 `evaluation/metrics/__init__.py`

**Files:**
- Create: `d:\EduRAG智慧问答系统\evaluation\metrics\__init__.py`

- [ ] **Step 1: 创建子包入口文件**

```python
"""
评估指标子包
提供三大类指标：检索指标、生成指标、LLM 评判指标
"""
from evaluation.metrics.retrieval import (
    calc_retrieval_metrics,
    calc_context_precision_embedding,
    calc_context_relevancy_embedding,
    RetrievalMetrics,
)
from evaluation.metrics.generation import (
    calc_bleu,
    calc_rouge_l,
    calc_keyword_match_rate,
    GenerationMetrics,
)
from evaluation.metrics.llm_judge import (
    calc_faithfulness,
    calc_answer_relevancy,
    calc_answer_correctness,
    RAGQualityMetrics,
)

__all__ = [
    "calc_retrieval_metrics",
    "calc_context_precision_embedding",
    "calc_context_relevancy_embedding",
    "RetrievalMetrics",
    "calc_bleu",
    "calc_rouge_l",
    "calc_keyword_match_rate",
    "GenerationMetrics",
    "calc_faithfulness",
    "calc_answer_relevancy",
    "calc_answer_correctness",
    "RAGQualityMetrics",
]
```

- [ ] **Step 2: Commit**

```bash
git add evaluation/metrics/__init__.py
git commit -m "feat: add evaluation metrics subpackage init"
```

---

### Task 2: 创建 `evaluation/metrics/retrieval.py`

**Files:**
- Create: `d:\EduRAG智慧问答系统\evaluation\metrics\retrieval.py`

- [ ] **Step 1: 创建检索指标模块**

从 `evaluator.py` 迁移 `RetrievalMetrics` dataclass 和 `evaluate_retrieval()` / `_calc_ndcg()` 逻辑，新增 embedding 相似度指标。

```python
"""
检索评估指标
- Precision@K, Recall@K, F1, MRR, NDCG, HitRate (doc_id/keyword matching)
- ContextPrecision, ContextRelevancy (embedding cosine similarity)
"""
import math
from typing import List, Optional
from dataclasses import dataclass, field
import numpy as np

from core.logger import get_logger

logger = get_logger("retrieval_metrics")


@dataclass
class RetrievalMetrics:
    """检索指标"""
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    hit_rate: float = 0.0
    context_precision: float = 0.0   # embedding 相似度均值
    context_relevancy: float = 0.0   # embedding 相似度均值


def calc_retrieval_metrics(
    retrieved_doc_ids: List[str],
    retrieved_contents: List[str],
    relevant_doc_ids: Optional[List[str]] = None,
    expected_keywords: Optional[List[str]] = None,
    top_k: int = 5,
) -> RetrievalMetrics:
    """
    计算检索指标

    Args:
        retrieved_doc_ids: 检索到的文档 ID 列表
        retrieved_contents: 检索到的文档内容列表
        relevant_doc_ids: 相关文档 ID 列表（精确匹配模式）
        expected_keywords: 期望关键词列表（回退模式）
        top_k: 评估的 Top-K 值

    Returns:
        RetrievalMetrics
    """
    if not retrieved_doc_ids:
        return RetrievalMetrics()

    retrieved_doc_ids = retrieved_doc_ids[:top_k]
    retrieved_contents = retrieved_contents[:top_k]

    # ── 相关性判定 ──
    has_doc_id_gt = bool(relevant_doc_ids)
    relevant_ids_set = set(relevant_doc_ids or [])

    if has_doc_id_gt:
        relevant_mask = [rid in relevant_ids_set for rid in retrieved_doc_ids]
        total_relevant = len(relevant_ids_set)
        matched_count = sum(1 for rid in retrieved_doc_ids if rid in relevant_ids_set)
    else:
        keywords = expected_keywords or []
        if keywords:
            relevant_mask = [
                any(kw.lower() in retrieved_contents[i].lower() for kw in keywords)
                for i in range(len(retrieved_doc_ids))
            ]
            all_content = " ".join(retrieved_contents).lower()
            matched_count = sum(1 for kw in keywords if kw.lower() in all_content)
            total_relevant = len(keywords)
        else:
            relevant_mask = [False] * len(retrieved_doc_ids)
            total_relevant = 0
            matched_count = 0

    retrieved_relevant = sum(1 for r in relevant_mask if r)

    # Precision
    precision = retrieved_relevant / len(retrieved_doc_ids) if retrieved_doc_ids else 0.0

    # Recall
    recall = matched_count / total_relevant if total_relevant > 0 else 0.0

    # F1
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # MRR
    mrr = 0.0
    for i, r in enumerate(relevant_mask):
        if r:
            mrr = 1.0 / (i + 1)
            break

    # NDCG
    ndcg = _calc_ndcg(relevant_mask, top_k)

    # HitRate
    hit_rate = 1.0 if retrieved_relevant > 0 else 0.0

    return RetrievalMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
        mrr=round(mrr, 4),
        ndcg=round(ndcg, 4),
        hit_rate=round(hit_rate, 4),
    )


def _calc_ndcg(relevant_mask: List[bool], k: int) -> float:
    """计算 NDCG@k"""
    relevance_scores = [1.0 if r else 0.0 for r in relevant_mask[:k]]
    ideal_relevance = sorted(relevance_scores, reverse=True)
    ideal_dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_relevance))
    if ideal_dcg == 0:
        return 0.0
    actual_dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevance_scores))
    return round(actual_dcg / ideal_dcg, 4)


def calc_context_precision_embedding(
    query: str,
    contexts: List[str],
    vectorizer=None,
) -> float:
    """
    用 embedding 余弦相似度计算 ContextPrecision
    = mean(query 与每个 context 的余弦相似度)

    Args:
        query: 查询文本
        contexts: 检索到的上下文列表
        vectorizer: Vectorizer 实例（不传则自动创建）

    Returns:
        0-1 之间的相似度均值
    """
    if not contexts:
        return 0.0

    if vectorizer is None:
        from data_processor.vectorizer import Vectorizer
        vectorizer = Vectorizer()

    try:
        query_emb = np.array(vectorizer.embed_query(query), dtype=np.float32)
        similarities = []
        for ctx in contexts:
            if not ctx.strip():
                similarities.append(0.0)
                continue
            ctx_emb = np.array(vectorizer.embed_query(ctx[:500]), dtype=np.float32)
            # 余弦相似度
            sim = np.dot(query_emb, ctx_emb) / (
                np.linalg.norm(query_emb) * np.linalg.norm(ctx_emb) + 1e-8
            )
            similarities.append(float(np.clip(sim, 0.0, 1.0)))
        return round(sum(similarities) / len(similarities), 4)
    except Exception as e:
        logger.warning(f"Embedding 相似度计算失败: {e}")
        return 0.0


# ContextRelevancy 与 ContextPrecision 在当前实现中相同（都是 query-context 相似度均值）
calc_context_relevancy_embedding = calc_context_precision_embedding
```

- [ ] **Step 2: Commit**

```bash
git add evaluation/metrics/retrieval.py
git commit -m "feat: add retrieval metrics module (precision/recall/mrr/ndcg + embedding similarity)"
```

---

### Task 3: 创建 `evaluation/metrics/generation.py`

**Files:**
- Create: `d:\EduRAG智慧问答系统\evaluation\metrics\generation.py`

- [ ] **Step 1: 创建生成指标模块**

从 `evaluator.py` 迁移 `_tokenize_jieba()`, `_calc_bleu()`, `_calc_rouge_l()`, `GenerationMetrics` dataclass 和关键词匹配率逻辑。

```python
"""
生成评估指标
- BLEU-1, BLEU-2 (jieba 分词)
- ROUGE-L (LCS 最长公共子序列)
- 关键词匹配率
"""
import math
from typing import List, Dict
from dataclasses import dataclass, field

from core.logger import get_logger

logger = get_logger("generation_metrics")


@dataclass
class GenerationMetrics:
    """生成指标"""
    bleu_1: float = 0.0
    bleu_2: float = 0.0
    rouge_l: float = 0.0
    keyword_match_rate: float = 0.0
    answer_length: int = 0
    llm_score: float = -1.0  # -1 表示未启用


def _tokenize_jieba(text: str) -> List[str]:
    """jieba 分词"""
    try:
        import jieba
        return list(jieba.cut(text.strip()))
    except ImportError:
        return list(text.strip())


def calc_bleu(reference: str, candidate: str, max_n: int = 2) -> Dict[str, float]:
    """
    计算 BLEU-1 和 BLEU-2（使用 jieba 分词）
    返回 {"bleu_1": float, "bleu_2": float}
    """
    if not candidate or not reference:
        return {"bleu_1": 0.0, "bleu_2": 0.0}

    ref_tokens = [_tokenize_jieba(reference)]
    cand_tokens = _tokenize_jieba(candidate)

    if len(cand_tokens) == 0:
        return {"bleu_1": 0.0, "bleu_2": 0.0}

    scores = {}
    for n in (1, 2):
        if len(cand_tokens) < n:
            scores[f"bleu_{n}"] = 0.0
            continue

        def _ngrams(tokens, n):
            return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]

        cand_ngrams = _ngrams(cand_tokens, n)
        ref_ngrams = _ngrams(ref_tokens[0], n)

        if not cand_ngrams:
            scores[f"bleu_{n}"] = 0.0
            continue

        ref_counts = {}
        for ng in ref_ngrams:
            ref_counts[ng] = ref_counts.get(ng, 0) + 1

        matches = 0
        cand_counts = {}
        for ng in cand_ngrams:
            cand_counts[ng] = cand_counts.get(ng, 0) + 1

        for ng, count in cand_counts.items():
            matches += min(count, ref_counts.get(ng, 0))

        precision = matches / len(cand_ngrams)
        bp = min(1.0, math.exp(1 - len(ref_tokens[0]) / max(len(cand_tokens), 1)))
        scores[f"bleu_{n}"] = round(bp * precision, 4)

    return scores


def calc_rouge_l(reference: str, candidate: str) -> float:
    """
    计算 ROUGE-L F1（基于最长公共子序列 LCS）
    中文单字切分，英文按空白切分
    """
    if not candidate or not reference:
        return 0.0

    def _tokenize(text: str) -> List[str]:
        tokens = []
        temp = ""
        for ch in text.lower().strip():
            if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf':
                if temp:
                    tokens.extend(temp.split())
                    temp = ""
                tokens.append(ch)
            else:
                temp += ch
        if temp:
            tokens.extend(temp.split())
        return tokens

    ref_tokens = _tokenize(reference)
    cand_tokens = _tokenize(candidate)

    if not ref_tokens or not cand_tokens:
        return 0.0

    m, n = len(ref_tokens), len(cand_tokens)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_tokens[i - 1] == cand_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_len = dp[m][n]
    if lcs_len == 0:
        return 0.0

    precision = lcs_len / len(cand_tokens)
    recall = lcs_len / len(ref_tokens)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return round(f1, 4)


def calc_keyword_match_rate(answer: str, expected_keywords: List[str]) -> float:
    """计算关键词匹配率"""
    if not expected_keywords:
        return 0.0
    hit_count = sum(1 for kw in expected_keywords if kw.lower() in answer.lower())
    return round(hit_count / len(expected_keywords), 4)
```

- [ ] **Step 2: Commit**

```bash
git add evaluation/metrics/generation.py
git commit -m "feat: add generation metrics module (bleu/rouge/keyword)"
```

---

### Task 4: 创建 `evaluation/metrics/llm_judge.py`

**Files:**
- Create: `d:\EduRAG智慧问答系统\evaluation\metrics\llm_judge.py`

- [ ] **Step 1: 创建 LLM 评判指标模块**

实现三种指标：
- Faithfulness: 分解评分（拆 claims → 逐条验证）
- AnswerRelevancy: Prompt 直出
- AnswerCorrectness: Prompt 直出（需 ground_truth）

```python
"""
LLM 评判指标
- Faithfulness (忠实度): 分解评分 — 拆 claims → 逐条验证
- AnswerRelevancy (答案相关性): Prompt 直出
- AnswerCorrectness (正确性): Prompt 直出（需 ground_truth）
"""
import json
import re
from typing import List, Optional
from dataclasses import dataclass, field

from core.logger import get_logger

logger = get_logger("llm_judge")


@dataclass
class RAGQualityMetrics:
    """RAG 质量指标"""
    faithfulness: float = 0.0       # 忠实度（分解评分）
    answer_relevancy: float = 0.0   # 答案相关性（prompt 直出）
    answer_correctness: float = 0.0 # 正确性（prompt 直出，需 ground_truth）


# ═══════════════════════════════════════════════════════════════
# Faithfulness — 分解评分
# ═══════════════════════════════════════════════════════════════

CLAIM_EXTRACTION_PROMPT = """你是一个严谨的事实核查助手。请将以下【答案】拆分为独立的、可验证的事实陈述（claims）。

【问题】
{question}

【答案】
{answer}

规则：
1. 每条 claim 必须是一个独立的事实陈述，可以单独验证真伪
2. 不要拆分同一个事实的不同表述方式
3. 如果答案中没有事实性陈述（如纯问候、纯闲聊），返回空列表
4. 每条 claim 用中文完整表述

返回严格 JSON 格式（不要 markdown 代码块）：
{{"claims": ["事实陈述1", "事实陈述2", ...]}}"""


CLAIM_VERIFICATION_PROMPT = """你是一个严谨的事实核查助手。请判断以下每条【事实陈述】是否被【参考资料】中的信息所支持。

【参考资料】
{contexts}

【事实陈述】
{claims_text}

规则：
1. 对每条陈述，判断参考资料中是否有明确信息支持它
2. "支持"意味着参考资料中包含了该陈述的核心事实，不需要逐字逐句相同
3. 如果参考资料完全没有提到相关事实，标记为"不支持"
4. 如果参考资料部分支持但不够充分，标记为"部分支持"

返回严格 JSON 格式：
{{"verifications": [
  {{"claim_index": 0, "supported": true, "reason": "一句话说明"}},
  {{"claim_index": 1, "supported": false, "reason": "一句话说明"}},
  ...
]}}"""


def _get_llm():
    """获取 LLM 客户端（qwen-turbo）"""
    from llm.llm_client import get_fast_llm
    return get_fast_llm()


def _extract_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if lines[0].startswith("```") else text
        if text.endswith("```"):
            text = text[:-3]
    # 尝试匹配 JSON 块
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        return json.loads(json_match.group())
    return {}


async def calc_faithfulness(
    question: str,
    answer: str,
    contexts: List[str],
    llm=None,
) -> float:
    """
    计算 Faithfulness（忠实度）— 分解评分

    1. LLM 将 answer 拆分为 claims
    2. LLM 逐条验证每一条 claim 是否被 contexts 支持
    3. 得分 = supported_count / total_count

    Args:
        question: 用户问题
        answer: 系统生成的答案
        contexts: 检索到的上下文列表
        llm: LLMClient 实例（不传则自动获取）

    Returns:
        0-1 之间的忠实度分数
    """
    if not answer or not contexts:
        return 0.0

    if llm is None:
        llm = _get_llm()

    try:
        # Step 1: 拆解 claims
        extract_prompt = CLAIM_EXTRACTION_PROMPT.format(
            question=question[:500],
            answer=answer[:1000],
        )
        extract_resp = llm.generate(extract_prompt, max_tokens=800, temperature=0.0)
        extract_data = _extract_json(extract_resp)
        claims = extract_data.get("claims", [])

        if not claims:
            return 1.0  # 无事实性陈述，默认忠实

        logger.info(f"[Faithfulness] 拆解出 {len(claims)} 条 claims")

        # Step 2: 逐条验证（批量一次请求）
        contexts_text = "\n\n---\n\n".join(
            f"[参考资料 {i+1}]\n{ctx[:500]}" for i, ctx in enumerate(contexts[:5])
        )
        claims_text = "\n".join(
            f"[{i}] {claim}" for i, claim in enumerate(claims)
        )
        verify_prompt = CLAIM_VERIFICATION_PROMPT.format(
            contexts=contexts_text[:3000],
            claims_text=claims_text,
        )
        verify_resp = llm.generate(verify_prompt, max_tokens=1000, temperature=0.0)
        verify_data = _extract_json(verify_resp)
        verifications = verify_data.get("verifications", [])

        if not verifications:
            return 0.0

        supported = sum(
            1 for v in verifications
            if v.get("supported") is True or v.get("supported") == "true"
        )
        score = supported / len(claims)
        logger.info(f"[Faithfulness] 得分: {supported}/{len(claims)} = {score:.4f}")
        return round(score, 4)

    except Exception as e:
        logger.warning(f"[Faithfulness] 计算失败: {e}")
        return 0.0


# ═══════════════════════════════════════════════════════════════
# AnswerRelevancy — Prompt 直出
# ═══════════════════════════════════════════════════════════════

ANSWER_RELEVANCY_PROMPT = """你是一个教育领域的答案质量评估专家。请评估以下【答案】与【问题】的相关程度。

【问题】
{question}

【答案】
{answer}

评估维度：
1. 答案是否直接回应了问题（不跑题、不绕弯）
2. 答案是否包含了与问题无关的冗余信息
3. 如果有冗余信息，是否影响了核心回答的清晰度

请给出 0-10 的整数评分，并简要说明理由。

返回严格 JSON 格式：
{{"score": <0-10的整数>, "relevant": <true/false>, "reason": "<一句话说明>"}}"""


async def calc_answer_relevancy(
    question: str,
    answer: str,
    llm=None,
) -> float:
    """
    计算 AnswerRelevancy（答案相关性）— Prompt 直出

    Args:
        question: 用户问题
        answer: 系统生成的答案
        llm: LLMClient 实例

    Returns:
        0-1 之间的相关性分数
    """
    if not answer:
        return 0.0

    if llm is None:
        llm = _get_llm()

    try:
        prompt = ANSWER_RELEVANCY_PROMPT.format(
            question=question[:500],
            answer=answer[:1000],
        )
        resp = llm.generate(prompt, max_tokens=300, temperature=0.0)
        data = _extract_json(resp)
        raw_score = float(data.get("score", 0))
        return round(raw_score / 10.0, 4)
    except Exception as e:
        logger.warning(f"[AnswerRelevancy] 计算失败: {e}")
        return 0.0


# ═══════════════════════════════════════════════════════════════
# AnswerCorrectness — Prompt 直出（需 ground_truth）
# ═══════════════════════════════════════════════════════════════

ANSWER_CORRECTNESS_PROMPT = """你是一个教育领域的答案评判专家。请对比【学生答案】与【标准答案】，评估学生答案的正确性。

【问题】
{question}

【标准答案】
{ground_truth}

【学生答案】
{answer}

请从以下维度评判（0-10分）：
1. 核心结论是否正确（关键事实、答案选项是否一致）
2. 推理过程是否合理（如有分析说明）
3. 是否包含无关或错误信息

返回 JSON 格式：
{{"score": <0-10的整数>, "correct": <true/false>, "reason": "<一句话说明>"}}

仅返回 JSON。"""


async def calc_answer_correctness(
    question: str,
    answer: str,
    ground_truth: str,
    llm=None,
) -> float:
    """
    计算 AnswerCorrectness（正确性）— Prompt 直出

    Args:
        question: 用户问题
        answer: 系统生成的答案
        ground_truth: 标准答案
        llm: LLMClient 实例

    Returns:
        0-1 之间的正确性分数
    """
    if not answer or not ground_truth:
        return 0.0

    if llm is None:
        llm = _get_llm()

    try:
        prompt = ANSWER_CORRECTNESS_PROMPT.format(
            question=question[:200],
            ground_truth=ground_truth[:500],
            answer=answer[:500],
        )
        resp = llm.generate(prompt, max_tokens=300, temperature=0.0)
        data = _extract_json(resp)
        raw_score = float(data.get("score", 0))
        return round(raw_score / 10.0, 4)
    except Exception as e:
        logger.warning(f"[AnswerCorrectness] 计算失败: {e}")
        return 0.0
```

- [ ] **Step 2: Commit**

```bash
git add evaluation/metrics/llm_judge.py
git commit -m "feat: add LLM judge metrics (faithfulness/relevancy/correctness)"
```

---

### Task 5: 创建 `evaluation/report.py`

**Files:**
- Create: `d:\EduRAG智慧问答系统\evaluation\report.py`

- [ ] **Step 1: 创建 HTML 报告生成模块**

从 `evaluator.py` 的 `generate_charts()` 迁移图表生成，新增完整的 HTML 报告模板。

```python
"""
评估报告生成
生成包含图表和指标详情的自包含 HTML 报告
"""
import base64
import io
import json
from typing import List, Dict, Optional
from dataclasses import dataclass

from core.logger import get_logger

logger = get_logger("eval_report")

# 尝试导入 matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    HAS_MATPLOTLIB = True

    _CN_FONTS = ["Noto Sans SC", "SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei"]
    for _fn in _CN_FONTS:
        try:
            fm.findfont(_fn, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [_fn]
            plt.rcParams["axes.unicode_minus"] = False
            break
        except Exception:
            continue
except ImportError:
    HAS_MATPLOTLIB = False


def _fig_to_b64(fig) -> str:
    """将 matplotlib figure 转为 base64 PNG"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def generate_charts(sample_reports: List[Dict]) -> Dict[str, str]:
    """生成评估图表，返回 {chart_name: base64_png}"""
    if not HAS_MATPLOTLIB or not sample_reports:
        return {}

    charts = {}
    n = len(sample_reports)

    try:
        # 图1: 检索指标柱状图
        fig, ax = plt.subplots(figsize=(8, 5))
        metrics_names = ["Precision", "Recall", "F1", "MRR", "NDCG", "HitRate"]
        values = [
            sum(r.get("precision", 0) for r in sample_reports) / n,
            sum(r.get("recall", 0) for r in sample_reports) / n,
            sum(r.get("f1", 0) for r in sample_reports) / n,
            sum(r.get("mrr", 0) for r in sample_reports) / n,
            sum(r.get("ndcg", 0) for r in sample_reports) / n,
            sum(r.get("hit_rate", 0) for r in sample_reports) / n,
        ]
        colors = ["#4CAF50", "#2196F3", "#FF9800", "#9C27B0", "#E91E63", "#00BCD4"]
        bars = ax.bar(metrics_names, values, color=colors, edgecolor="white")
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                    f"{val:.2%}", ha="center", va="bottom", fontsize=10)
        ax.set_ylim(0, 1.15)
        ax.set_title("Retrieval Metrics", fontsize=14, fontweight="bold")
        ax.set_ylabel("Score")
        fig.tight_layout()
        charts["retrieval"] = _fig_to_b64(fig)
        plt.close(fig)

        # 图2: 生成指标条形图
        top_n = min(20, n)
        display = sample_reports[:top_n]
        queries = [r.get("query", "")[:15] + "..." for r in display]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        bleu_vals = [r.get("bleu_1", 0) for r in display]
        rouge_vals = [r.get("rouge_l", 0) for r in display]
        x = range(len(queries))
        width = 0.35
        ax1.barh([i + width / 2 for i in x], bleu_vals, width, label="BLEU-1", color="#2196F3")
        ax1.barh([i - width / 2 for i in x], rouge_vals, width, label="ROUGE-L", color="#4CAF50")
        ax1.set_yticks(x)
        ax1.set_yticklabels(queries, fontsize=8)
        ax1.set_xlabel("Score")
        ax1.set_title("BLEU-1 & ROUGE-L", fontsize=12, fontweight="bold")
        ax1.set_xlim(0, 1.1)
        ax1.legend(fontsize=8)

        kw_rates = [r.get("keyword_match_rate", 0) for r in display]
        ax2.barh(range(len(queries)), kw_rates, color="#FF9800")
        ax2.set_yticks(range(len(queries)))
        ax2.set_yticklabels(queries, fontsize=8)
        ax2.set_xlabel("Keyword Match Rate")
        ax2.set_title("Keyword Match Rate", fontsize=12, fontweight="bold")
        ax2.set_xlim(0, 1.1)
        fig.tight_layout()
        charts["generation"] = _fig_to_b64(fig)
        plt.close(fig)

    except Exception as e:
        logger.warning(f"Chart generation failed: {e}")

    return charts


def format_report_html(
    metrics: Dict,
    details: List[Dict],
    total_time: float,
    charts: Dict[str, str] = None,
) -> str:
    """
    生成统一 HTML 评估报告

    Args:
        metrics: 汇总指标 dict
        details: 逐样本详情列表
        total_time: 总耗时（秒）
        charts: 图表 base64 dict

    Returns:
        HTML 字符串
    """
    charts = charts or {}

    def _bar(val, color=None):
        pct = int(val * 100)
        if color is None:
            color = "#4CAF50" if val >= 0.7 else "#FF9800" if val >= 0.4 else "#F44336"
        return (
            f"<div style='display:flex;align-items:center;gap:8px;'>"
            f"<div style='flex:1;background:#e0e0e0;border-radius:3px;height:10px;'>"
            f"<div style='width:{pct}%;background:{color};border-radius:3px;height:10px;'></div>"
            f"</div><span style='min-width:50px;font-weight:bold;color:{color};'>{val:.1%}</span></div>"
        )

    def _card(title, value, color, unit=""):
        return (
            f"<div style='flex:1;min-width:80px;background:{color};border-radius:8px;"
            f"padding:12px;text-align:center;'>"
            f"<div style='font-size:11px;color:#666;'>{title}</div>"
            f"<div style='font-size:24px;font-weight:bold;color:#333;'>{value}{unit}</div></div>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EduRAG 评估报告</title>
<style>
* {{margin:0;padding:0;box-sizing:border-box;}}
body {{font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;background:#f5f7fa;color:#333;padding:24px;}}
.container {{max-width:1200px;margin:0 auto;}}
h1 {{font-size:24px;margin-bottom:20px;color:#1a1a2e;}}
h2 {{font-size:18px;margin:24px 0 12px;color:#1a1a2e;border-bottom:2px solid #e0e0e0;padding-bottom:6px;}}
.card {{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,0.06);}}
.metric-row {{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;}}
.chart-img {{max-width:100%;border-radius:8px;margin:8px 0;}}
.sample-detail {{font-size:13px;}}
.sample-detail summary {{cursor:pointer;padding:8px;background:#f0f4f8;border-radius:6px;margin:4px 0;}}
.sample-detail table {{width:100%;border-collapse:collapse;margin:8px 0;}}
.sample-detail th, .sample-detail td {{padding:6px 10px;text-align:left;border-bottom:1px solid #eee;font-size:12px;}}
.sample-detail th {{background:#f8f9fa;font-weight:600;}}
</style>
</head>
<body>
<div class="container">
<h1>EduRAG 统一评估报告</h1>
"""

    # 概览卡片
    sample_count = details and len(details) or 0
    avg_score = metrics.get("avg_score", 0)
    html += "<div class='card'><div class='metric-row'>"
    html += _card("样本数", sample_count, "#e3f2fd")
    html += _card("平均分", f"{avg_score:.1%}", "#e8f5e9")
    html += _card("总耗时", f"{total_time:.1f}s", "#fff3e0")
    html += "</div></div>"

    # 检索指标
    html += "<h2>检索指标</h2><div class='card'>"
    r = metrics.get("retrieval", {})
    retrieval_items = [
        ("Precision", r.get("precision", 0), "检索结果中相关文档的比例"),
        ("Recall", r.get("recall", 0), "所有相关文档被检索到的比例"),
        ("F1 Score", r.get("f1_score", 0), "Precision 与 Recall 的调和平均"),
        ("MRR", r.get("mrr", 0), "第一个相关文档排名的倒数均值"),
        ("NDCG", r.get("ndcg", 0), "归一化折损累计增益"),
        ("Hit Rate", r.get("hit_rate", 0), "至少命中一个相关文档的概率"),
    ]
    for name, val, desc in retrieval_items:
        html += f"<div style='margin:8px 0;'><div style='display:flex;justify-content:space-between;'><span><b>{name}</b></span><span style='font-size:12px;color:#999;'>{desc}</span></div>{_bar(val)}</div>"
    r2 = metrics.get("rag_quality", {})
    html += f"<div style='margin:8px 0;'><div style='display:flex;justify-content:space-between;'><span><b>ContextPrecision</b></span><span style='font-size:12px;color:#999;'>embedding 相似度均值</span></div>{_bar(r2.get('context_precision', 0))}</div>"
    if charts.get("retrieval"):
        html += f"<img class='chart-img' src='data:image/png;base64,{charts['retrieval']}' alt='检索指标图表'>"
    html += "</div>"

    # 生成指标
    html += "<h2>生成指标</h2><div class='card'>"
    g = metrics.get("generation", {})
    gen_items = [
        ("BLEU-1", g.get("bleu_1", 0)),
        ("BLEU-2", g.get("bleu_2", 0)),
        ("ROUGE-L", g.get("rouge_l", 0)),
        ("关键词匹配率", g.get("keyword_match_rate", 0)),
    ]
    for name, val in gen_items:
        html += f"<div style='margin:8px 0;'><div style='display:flex;justify-content:space-between;'><span><b>{name}</b></span></div>{_bar(val)}</div>"
    if charts.get("generation"):
        html += f"<img class='chart-img' src='data:image/png;base64,{charts['generation']}' alt='生成指标图表'>"
    html += "</div>"

    # RAG 质量指标
    html += "<h2>RAG 质量指标 (LLM 评判)</h2><div class='card'>"
    q = metrics.get("rag_quality", {})
    rag_items = [
        ("Faithfulness (忠实度)", q.get("faithfulness", 0), "答案是否忠实于上下文，不编造"),
        ("AnswerRelevancy (答案相关性)", q.get("answer_relevancy", 0), "答案是否直接回应问题"),
        ("AnswerCorrectness (正确性)", q.get("answer_correctness", 0), "与标准答案的一致性"),
    ]
    for name, val, desc in rag_items:
        html += f"<div style='margin:8px 0;'><div style='display:flex;justify-content:space-between;'><span><b>{name}</b></span><span style='font-size:12px;color:#999;'>{desc}</span></div>{_bar(val)}</div>"
    html += "</div>"

    # 样本详情
    html += "<h2>样本详情</h2><div class='card sample-detail'>"
    for i, d in enumerate(details):
        query = d.get("query", "")[:80]
        answer = (d.get("answer", "") or "")[:150]
        html += f"<details><summary>[{i+1}] {query}</summary>"
        html += "<table>"
        html += f"<tr><th>字段</th><th>值</th></tr>"
        html += f"<tr><td>答案</td><td>{answer}</td></tr>"
        for key in ["bleu_1", "bleu_2", "rouge_l", "keyword_match_rate", "f1", "precision", "recall", "mrr", "execution_time"]:
            if key in d:
                val = d[key]
                if isinstance(val, float):
                    val = f"{val:.4f}"
                html += f"<tr><td>{key}</td><td>{val}</td></tr>"
        html += "</table></details>"
    html += "</div>"

    html += "</div></body></html>"
    return html
```

- [ ] **Step 2: Commit**

```bash
git add evaluation/report.py
git commit -m "feat: add HTML report generation module"
```

---

### Task 6: 创建 `evaluation/unified_evaluator.py`

**Files:**
- Create: `d:\EduRAG智慧问答系统\evaluation\unified_evaluator.py`

- [ ] **Step 1: 创建统一评估器主入口**

整合 `evaluator.py` 的查询采集逻辑和 `ragas_evaluator.py` 的流式评估逻辑，底层调用 `metrics/` 子包计算指标。

```python
"""
统一评估器
合并 evaluator.py 和 ragas_evaluator.py 的功能，提供同步+流式双入口

用法:
    evaluator = UnifiedEvaluator()
    report = await evaluator.evaluate(test_cases, query_func)
    # 或
    async for event in evaluator.evaluate_stream(test_cases, query_func):
        yield event
"""
import asyncio
import concurrent.futures
import math
import queue as queue_module
import time
from typing import List, Dict, Optional, Callable, AsyncGenerator, Any
from dataclasses import dataclass, field

from core.logger import get_logger
from evaluation.metrics.retrieval import (
    calc_retrieval_metrics,
    calc_context_precision_embedding,
    RetrievalMetrics,
)
from evaluation.metrics.generation import (
    calc_bleu,
    calc_rouge_l,
    calc_keyword_match_rate,
    GenerationMetrics,
)
from evaluation.metrics.llm_judge import (
    calc_faithfulness,
    calc_answer_relevancy,
    calc_answer_correctness,
    RAGQualityMetrics,
)
from evaluation.report import generate_charts, format_report_html

logger = get_logger("unified_evaluator")


@dataclass
class EvalConfig:
    """评估配置"""
    metrics: List[str] = field(default_factory=lambda: [
        "retrieval", "generation", "faithfulness", "answer_relevancy"
    ])
    top_k: int = 5
    parallel_queries: int = 8
    parallel_scoring: int = 4
    use_llm_judge: bool = True
    max_samples: int = 0  # 0 = 不限制


@dataclass
class SampleScore:
    """单样本指标得分"""
    query: str = ""
    answer: str = ""
    contexts: List[str] = field(default_factory=list)
    ground_truth: str = ""
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    generation: GenerationMetrics = field(default_factory=GenerationMetrics)
    rag_quality: RAGQualityMetrics = field(default_factory=RAGQualityMetrics)
    execution_time: float = 0.0


@dataclass
class EvalReport:
    """完整评估报告"""
    config: EvalConfig = field(default_factory=EvalConfig)
    sample_count: int = 0
    total_time: float = 0.0
    avg_metrics: Dict = field(default_factory=dict)
    sample_scores: List[SampleScore] = field(default_factory=list)
    charts: Dict[str, str] = field(default_factory=dict)


class UnifiedEvaluator:
    """统一评估器"""

    def __init__(self, config: EvalConfig = None):
        self.config = config or EvalConfig()
        self._llm = None
        self._vectorizer = None

    @property
    def llm(self):
        if self._llm is None and self.config.use_llm_judge:
            from llm.llm_client import get_fast_llm
            self._llm = get_fast_llm()
        return self._llm

    @property
    def vectorizer(self):
        if self._vectorizer is None:
            from data_processor.vectorizer import Vectorizer
            self._vectorizer = Vectorizer()
        return self._vectorizer

    # ═══════════════════════════════════════════════════════════
    # 同步入口
    # ═══════════════════════════════════════════════════════════

    async def evaluate(
        self,
        test_cases: List[Dict],
        query_func: Callable,
    ) -> EvalReport:
        """
        阶段一：并行采集 → 阶段二：批量计算指标 → 返回报告

        Args:
            test_cases: [{"question": "...", "ground_truth": "...", "relevant_doc_ids": [...], "expected_keywords": [...]}]
            query_func: async or sync function(query: str) -> response with .answer and .sources

        Returns:
            EvalReport
        """
        if self.config.max_samples > 0:
            test_cases = test_cases[:self.config.max_samples]

        t0 = time.time()

        # 阶段一：并行采集
        samples = await self._collect_samples(test_cases, query_func)
        if not samples:
            return EvalReport(config=self.config, total_time=time.time() - t0)

        # 阶段二：批量计算指标
        sample_scores = await self._score_all(samples)

        # 汇总
        avg_metrics = self._aggregate_metrics(sample_scores)
        total_time = time.time() - t0

        # 图表
        sample_reports = [self._score_to_dict(s) for s in sample_scores]
        charts = generate_charts(sample_reports)

        report = EvalReport(
            config=self.config,
            sample_count=len(sample_scores),
            total_time=round(total_time, 2),
            avg_metrics=avg_metrics,
            sample_scores=sample_scores,
            charts=charts,
        )

        logger.info(
            f"评估完成: {len(sample_scores)} 个样本, {total_time:.1f}s, "
            f"avg_score={avg_metrics.get('avg_score', 0):.4f}"
        )
        return report

    # ═══════════════════════════════════════════════════════════
    # 流式入口
    # ═══════════════════════════════════════════════════════════

    async def evaluate_stream(
        self,
        test_cases: List[Dict],
        query_func: Callable,
        cancel_event=None,
    ) -> AsyncGenerator[Dict, None]:
        """
        逐样本采集+计算 → 实时 yield SSE 事件

        Yields:
            {"event": "progress", ...}
            {"event": "sample_done", ...}
            {"event": "evaluating", ...}
            {"event": "complete", ...}
        """
        if self.config.max_samples > 0:
            test_cases = test_cases[:self.config.max_samples]

        t0 = time.time()
        sample_scores = []
        total = len(test_cases)

        yield {"event": "evaluating", "message": "开始评测...", "total": total}

        # 逐样本采集 + 计算
        for i, tc in enumerate(test_cases):
            if cancel_event and cancel_event.is_set():
                yield {"event": "cancelled", "current": i, "total": total}
                logger.info("评测已被取消")
                return

            yield {"event": "progress", "current": i + 1, "total": total,
                   "question": tc.get("question", "")[:60]}

            t_sample = time.time()
            try:
                # 查询
                if asyncio.iscoroutinefunction(query_func):
                    response = await query_func(tc["question"])
                else:
                    response = await asyncio.to_thread(query_func, tc["question"])

                answer = response.answer if hasattr(response, 'answer') else ""
                sources = response.sources if hasattr(response, 'sources') else []
                contexts = [
                    s.chunk.content if hasattr(s, 'chunk') and hasattr(s.chunk, 'content')
                    else str(s.chunk) if hasattr(s, 'chunk')
                    else str(s)
                    for s in sources[:self.config.top_k]
                ]
                exec_time = time.time() - t_sample

                # 计算指标
                score = await self._score_one(
                    question=tc["question"],
                    answer=answer,
                    contexts=contexts,
                    ground_truth=tc.get("ground_truth", ""),
                    relevant_doc_ids=tc.get("relevant_doc_ids"),
                    expected_keywords=tc.get("expected_keywords"),
                    expected_answer=tc.get("expected_answer", ""),
                    exec_time=exec_time,
                )
                sample_scores.append(score)

                # 累积指标
                cumulative = self._aggregate_metrics(sample_scores)

                yield {
                    "event": "sample_done",
                    "index": i,
                    "question": tc["question"][:60],
                    "score": self._score_to_dict(score),
                    "cumulative": cumulative,
                }

            except Exception as e:
                logger.error(f"样本 {i} 评测失败: {e}")
                yield {
                    "event": "sample_done",
                    "index": i,
                    "question": tc.get("question", "")[:60],
                    "error": str(e),
                }

        # 最终汇总
        avg_metrics = self._aggregate_metrics(sample_scores)
        sample_reports = [self._score_to_dict(s) for s in sample_scores]
        charts = generate_charts(sample_reports)

        total_time = time.time() - t0
        yield {
            "event": "complete",
            "sample_count": len(sample_scores),
            "total_time": round(total_time, 2),
            "metrics": avg_metrics,
            "details": sample_reports,
            "charts": charts,
            "mode": "unified",
        }

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    async def _collect_samples(
        self,
        test_cases: List[Dict],
        query_func: Callable,
        cancel_event=None,
    ) -> List[Dict]:
        """并行查询采集 samples"""
        async def _query_one(tc):
            if cancel_event and cancel_event.is_set():
                return None
            try:
                if asyncio.iscoroutinefunction(query_func):
                    response = await query_func(tc["question"])
                else:
                    response = await asyncio.to_thread(query_func, tc["question"])

                answer = response.answer if hasattr(response, 'answer') else ""
                sources = response.sources if hasattr(response, 'sources') else []
                contexts = [
                    s.chunk.content if hasattr(s, 'chunk') and hasattr(s.chunk, 'content')
                    else str(s.chunk) if hasattr(s, 'chunk')
                    else str(s)
                    for s in sources[:self.config.top_k]
                ]
                return {
                    "question": tc["question"],
                    "answer": answer,
                    "contexts": contexts,
                    "ground_truth": tc.get("ground_truth", ""),
                    "relevant_doc_ids": tc.get("relevant_doc_ids"),
                    "expected_keywords": tc.get("expected_keywords"),
                    "expected_answer": tc.get("expected_answer", ""),
                }
            except Exception as e:
                logger.error(f"查询失败 [{tc.get('question', '')[:40]}]: {e}")
                return None

        sem = asyncio.Semaphore(self.config.parallel_queries)

        async def _limited_query(tc):
            async with sem:
                return await _query_one(tc)

        tasks = [_limited_query(tc) for tc in test_cases]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _score_all(self, samples: List[Dict]) -> List[SampleScore]:
        """并行计算所有样本的指标"""
        sem = asyncio.Semaphore(self.config.parallel_scoring)

        async def _limited_score(sample):
            async with sem:
                return await self._score_one(**sample)

        tasks = [_limited_score(s) for s in samples]
        return await asyncio.gather(*tasks)

    async def _score_one(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: str = "",
        relevant_doc_ids: List[str] = None,
        expected_keywords: List[str] = None,
        expected_answer: str = "",
        exec_time: float = 0.0,
    ) -> SampleScore:
        """计算单个样本的全部指标"""
        # 检索指标
        retrieved_ids = [f"ctx_{i}" for i in range(len(contexts))]
        retrieval = calc_retrieval_metrics(
            retrieved_doc_ids=retrieved_ids,
            retrieved_contents=contexts,
            relevant_doc_ids=relevant_doc_ids,
            expected_keywords=expected_keywords,
            top_k=self.config.top_k,
        )

        # Embedding 相似度指标（无 ground_truth 时可用）
        if question and contexts:
            retrieval.context_precision = calc_context_precision_embedding(
                question, contexts, self.vectorizer
            )
            retrieval.context_relevancy = retrieval.context_precision

        # 生成指标
        gen = GenerationMetrics(answer_length=len(answer))
        if expected_answer:
            bleu = calc_bleu(expected_answer, answer)
            gen.bleu_1 = bleu.get("bleu_1", 0.0)
            gen.bleu_2 = bleu.get("bleu_2", 0.0)
            gen.rouge_l = calc_rouge_l(expected_answer, answer)
        if expected_keywords:
            gen.keyword_match_rate = calc_keyword_match_rate(answer, expected_keywords)

        # LLM 评判指标
        rag = RAGQualityMetrics()
        if self.config.use_llm_judge and answer and "faithfulness" in self.config.metrics:
            rag.faithfulness = await calc_faithfulness(question, answer, contexts, self.llm)
        if self.config.use_llm_judge and answer and "answer_relevancy" in self.config.metrics:
            rag.answer_relevancy = await calc_answer_relevancy(question, answer, self.llm)
        if self.config.use_llm_judge and ground_truth and answer and "answer_correctness" in self.config.metrics:
            rag.answer_correctness = await calc_answer_correctness(question, answer, ground_truth, self.llm)

        return SampleScore(
            query=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
            retrieval=retrieval,
            generation=gen,
            rag_quality=rag,
            execution_time=exec_time,
        )

    def _aggregate_metrics(self, sample_scores: List[SampleScore]) -> Dict:
        """汇总多样本指标为平均值"""
        if not sample_scores:
            return {}

        n = len(sample_scores)
        retrieval = {
            "precision": round(sum(s.retrieval.precision for s in sample_scores) / n, 4),
            "recall": round(sum(s.retrieval.recall for s in sample_scores) / n, 4),
            "f1_score": round(sum(s.retrieval.f1_score for s in sample_scores) / n, 4),
            "mrr": round(sum(s.retrieval.mrr for s in sample_scores) / n, 4),
            "ndcg": round(sum(s.retrieval.ndcg for s in sample_scores) / n, 4),
            "hit_rate": round(sum(s.retrieval.hit_rate for s in sample_scores) / n, 4),
        }
        generation = {
            "bleu_1": round(sum(s.generation.bleu_1 for s in sample_scores) / n, 4),
            "bleu_2": round(sum(s.generation.bleu_2 for s in sample_scores) / n, 4),
            "rouge_l": round(sum(s.generation.rouge_l for s in sample_scores) / n, 4),
            "keyword_match_rate": round(sum(s.generation.keyword_match_rate for s in sample_scores) / n, 4),
            "avg_answer_length": sum(s.generation.answer_length for s in sample_scores) // n,
        }
        rag_quality = {
            "faithfulness": round(sum(s.rag_quality.faithfulness for s in sample_scores) / n, 4),
            "answer_relevancy": round(sum(s.rag_quality.answer_relevancy for s in sample_scores) / n, 4),
            "answer_correctness": round(sum(s.rag_quality.answer_correctness for s in sample_scores) / n, 4),
            "context_precision": round(sum(s.retrieval.context_precision for s in sample_scores) / n, 4),
            "context_relevancy": round(sum(s.retrieval.context_relevancy for s in sample_scores) / n, 4),
        }

        # 综合平均分
        all_scores = []
        all_scores.extend(retrieval.values())
        all_scores.extend(generation.values())
        all_scores.extend([v for v in rag_quality.values() if v > 0])
        avg_score = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0

        return {
            "retrieval": retrieval,
            "generation": generation,
            "rag_quality": rag_quality,
            "avg_score": avg_score,
        }

    def _score_to_dict(self, score: SampleScore) -> Dict:
        """将 SampleScore 转为可序列化字典"""
        return {
            "query": score.query[:80],
            "answer": score.answer[:300],
            "context_count": len(score.contexts),
            "ground_truth": score.ground_truth[:100],
            "precision": score.retrieval.precision,
            "recall": score.retrieval.recall,
            "f1": score.retrieval.f1_score,
            "mrr": score.retrieval.mrr,
            "ndcg": score.retrieval.ndcg,
            "hit_rate": score.retrieval.hit_rate,
            "context_precision": score.retrieval.context_precision,
            "bleu_1": score.generation.bleu_1,
            "bleu_2": score.generation.bleu_2,
            "rouge_l": score.generation.rouge_l,
            "keyword_match_rate": score.generation.keyword_match_rate,
            "faithfulness": score.rag_quality.faithfulness,
            "answer_relevancy": score.rag_quality.answer_relevancy,
            "answer_correctness": score.rag_quality.answer_correctness,
            "execution_time": round(score.execution_time, 2),
        }

    def format_report(self, report: EvalReport) -> str:
        """生成 HTML 报告"""
        details = [self._score_to_dict(s) for s in report.sample_scores]
        return format_report_html(
            metrics=report.avg_metrics,
            details=details,
            total_time=report.total_time,
            charts=report.charts,
        )
```

- [ ] **Step 2: Verify the file parses correctly**

Run: `python -c "from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig, EvalReport; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add evaluation/unified_evaluator.py
git commit -m "feat: add unified evaluator (sync + stream entry points)"
```

---

### Task 7: 更新 `evaluation/evaluator.py` — 标记废弃

**Files:**
- Modify: `d:\EduRAG智慧问答系统\evaluation\evaluator.py`

- [ ] **Step 1: 在文件顶部添加废弃警告，内部转调 unified_evaluator**

保留 `EvalSample`, `RetrievalMetrics`, `GenerationMetrics`, `EvalReport` dataclass 和 `generate_charts()`, `print_report()` 的签名兼容，但 `RAGEvaluator` 内部转调 `UnifiedEvaluator`。

在 `evaluator.py` 文件顶部（import 之后）添加：

```python
import warnings
warnings.warn(
    "evaluator.py is deprecated. Use evaluation.unified_evaluator.UnifiedEvaluator instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

修改 `RAGEvaluator.run_full_evaluation()` 方法委托给 `UnifiedEvaluator`：

```python
def run_full_evaluation(self, query_func: Callable[[str], any]) -> EvalReport:
    """
    运行完整评估（已委托给 UnifiedEvaluator）
    """
    import asyncio
    from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig

    test_cases = [
        {
            "question": s.query,
            "expected_answer": s.expected_answer,
            "expected_keywords": s.expected_keywords,
            "relevant_doc_ids": s.relevant_doc_ids,
        }
        for s in self.samples
    ]

    evaluator = UnifiedEvaluator(EvalConfig(use_llm_judge=self.use_llm_judge))
    unified_report = asyncio.run(evaluator.evaluate(test_cases, query_func))

    # 转换回旧格式
    avg_r = RetrievalMetrics(
        precision=unified_report.avg_metrics["retrieval"]["precision"],
        recall=unified_report.avg_metrics["retrieval"]["recall"],
        f1_score=unified_report.avg_metrics["retrieval"]["f1_score"],
        mrr=unified_report.avg_metrics["retrieval"]["mrr"],
        ndcg=unified_report.avg_metrics["retrieval"]["ndcg"],
        hit_rate=unified_report.avg_metrics["retrieval"]["hit_rate"],
    )
    avg_g = GenerationMetrics(
        bleu_1=unified_report.avg_metrics["generation"]["bleu_1"],
        bleu_2=unified_report.avg_metrics["generation"]["bleu_2"],
        rouge_l=unified_report.avg_metrics["generation"]["rouge_l"],
        keyword_match_rate=unified_report.avg_metrics["generation"]["keyword_match_rate"],
        answer_length=unified_report.avg_metrics["generation"].get("avg_answer_length", 0),
        avg_execution_time=unified_report.total_time / max(unified_report.sample_count, 1),
    )

    return EvalReport(
        retrieval=avg_r,
        generation=avg_g,
        sample_count=unified_report.sample_count,
        total_time=unified_report.total_time,
        sample_reports=[unified_evaluator._score_to_dict(s) for s in unified_report.sample_scores],
        charts=unified_report.charts,
    )
```

同样的委托方式修改 `run_full_evaluation_stream()`。

- [ ] **Step 2: Verify import still works**

Run: `python -c "from evaluation.evaluator import RAGEvaluator, EvalSample; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add evaluation/evaluator.py
git commit -m "refactor: mark evaluator.py deprecated, delegate to UnifiedEvaluator"
```

---

### Task 8: 删除 `evaluation/ragas_evaluator.py`

**Files:**
- Delete: `d:\EduRAG智慧问答系统\evaluation\ragas_evaluator.py`

- [ ] **Step 1: 删除文件**

```bash
git rm evaluation/ragas_evaluator.py
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: remove ragas_evaluator.py (replaced by unified_evaluator.py)"
```

---

### Task 9: 更新 `api/admin_routes.py`

**Files:**
- Modify: `d:\EduRAG智慧问答系统\api\admin_routes.py`

- [ ] **Step 1: 删除 ragas 相关导入和端点，重写 `/evaluate/ragas` 和 `/evaluate/ragas/stream`**

1. 删除 `RAGASEvalRequest` 类（行 385-389）
2. 将 `POST /evaluate/ragas`（行 392-454）改为调用 `UnifiedEvaluator`
3. 将 `GET /evaluate/ragas/stream`（行 586-669）改为调用 `UnifiedEvaluator.evaluate_stream()`
4. 保留 `GET /evaluate/ragas/samples`（行 457-473），路径改为 `/evaluate/samples`

新 `POST /evaluate/run` 端点（替换旧的 `/evaluate/ragas`）：

```python
class EvalRequest(BaseModel):
    """统一评测请求"""
    test_cases: List[dict] = Field(default_factory=list, description="自定义测试样本")
    metrics: List[str] = Field(default_factory=lambda: ["retrieval", "generation", "faithfulness", "answer_relevancy"],
                               description="要计算的指标")
    max_samples: int = Field(default=0, ge=0, description="最多评测样本数")
    use_llm_judge: bool = Field(default=True, description="是否启用 LLM 评判")
    parallel_queries: int = Field(default=8, ge=1, le=16)
    parallel_scoring: int = Field(default=4, ge=1, le=8)


@admin_router.post("/evaluate/run")
async def run_evaluation(request: EvalRequest = None, admin: dict = Depends(require_admin)):
    """运行统一评测"""
    try:
        from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig

        config = EvalConfig(
            metrics=request.metrics if request else ["retrieval", "generation", "faithfulness", "answer_relevancy"],
            max_samples=request.max_samples if request else 0,
            parallel_queries=request.parallel_queries if request else 8,
            parallel_scoring=request.parallel_scoring if request else 4,
            use_llm_judge=request.use_llm_judge if request else True,
        )
        evaluator = UnifiedEvaluator(config)
        query_func = _make_query_func()

        test_cases = []
        if request and request.test_cases:
            test_cases = request.test_cases
        else:
            test_cases = _load_builtin_samples()

        report = await evaluator.evaluate(test_cases, query_func)

        return {
            "metrics": report.avg_metrics,
            "sample_count": report.sample_count,
            "total_time": report.total_time,
            "details": [evaluator._score_to_dict(s) for s in report.sample_scores],
            "mode": "unified",
        }
    except Exception as e:
        logger.error(f"评测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"评测失败: {str(e)}")
```

新 `GET /evaluate/stream` 端点（替换旧的 `/evaluate/ragas/stream`）：

```python
@admin_router.get("/evaluate/stream")
async def evaluate_stream_v2(
    admin: dict = Depends(require_admin),
    max_samples: int = Query(0, ge=0, description="最多评测样本数"),
    metrics: str = Query("retrieval,generation,faithfulness,answer_relevancy",
                         description="指标列表，逗号分隔"),
):
    """流式统一评测（SSE）"""
    import json as _json

    session_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    _running_evals[session_id] = cancel_event
    event_queue = queue_module.Queue()

    def _run():
        try:
            from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig

            metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
            config = EvalConfig(
                metrics=metric_list,
                max_samples=max_samples,
                use_llm_judge=True,
            )
            evaluator = UnifiedEvaluator(config)
            query_func = _make_query_func()
            test_cases = _load_builtin_samples()

            async def _run_stream():
                async for evt in evaluator.evaluate_stream(
                    test_cases, query_func, cancel_event=cancel_event
                ):
                    event_queue.put(evt)

            asyncio.run(_run_stream())
        except Exception as e:
            logger.error(f"流式评测异常: {e}", exc_info=True)
            event_queue.put({"event": "error", "message": str(e)})

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    async def event_generator():
        yield f"event: connected\ndata: {_json.dumps({'event': 'connected', 'session_id': session_id, 'message': '统一评测引擎已就绪'}, ensure_ascii=False)}\n\n"

        while thread.is_alive() or not event_queue.empty():
            try:
                evt = await asyncio.to_thread(event_queue.get, True, 0.3)
            except queue_module.Empty:
                yield f": heartbeat {int(time.time())}\n\n"
                continue

            if evt.get("event") == "complete":
                try:
                    db = MySQLDB()
                    db.insert_eval_history(
                        history_id=session_id,
                        eval_type="unified",
                        config={"metrics": metric_list, "max_samples": max_samples},
                        metrics=evt.get("metrics", {}),
                        details=evt.get("details", []),
                        sample_count=evt.get("sample_count", 0),
                        total_time=evt.get("total_time", 0),
                        mode="unified",
                    )
                except Exception as e:
                    logger.error(f"保存评测历史失败: {e}")

            yield f"event: {evt.get('event', 'message')}\ndata: {_json.dumps(evt, ensure_ascii=False)}\n\n"

        if session_id in _running_evals:
            del _running_evals[session_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
```

添加 `_load_builtin_samples()` 辅助函数：

```python
def _load_builtin_samples() -> List[dict]:
    """加载内置测试样本"""
    test_set_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "evaluation", "k12_test_set.json"
    )
    if os.path.exists(test_set_path):
        with open(test_set_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [
            {
                "question": item["query"],
                "ground_truth": item.get("expected_answer", ""),
                "expected_answer": item.get("expected_answer", ""),
                "expected_keywords": item.get("expected_keywords", []),
                "relevant_doc_ids": item.get("relevant_doc_ids", []),
            }
            for item in raw
        ]

    # 回退：内置默认样本
    return [
        {"question": "什么是素质教育？",
         "ground_truth": "素质教育是注重学生全面发展的教育理念，强调德智体美劳全面发展。",
         "expected_answer": "素质教育是注重学生全面发展的教育理念，强调德智体美劳全面发展。"},
        {"question": "如何提高学生的学习兴趣？",
         "ground_truth": "通过多样化教学方式、创设情境、激发好奇心等方法提高学习兴趣。",
         "expected_answer": "通过多样化教学方式、创设情境、激发好奇心等方法提高学习兴趣。"},
        {"question": "在线教育的优缺点是什么？",
         "ground_truth": "在线教育的优点包括灵活便捷、资源丰富；缺点包括缺乏互动、自律要求高。",
         "expected_answer": "在线教育的优点包括灵活便捷、资源丰富；缺点包括缺乏互动、自律要求高。"},
    ]
```

- [ ] **Step 2: 保留旧端点兼容**

保留 `POST /evaluate/ragas` 和 `GET /evaluate/ragas/stream` 的重定向到新端点，添加废弃警告：

```python
@admin_router.post("/evaluate/ragas")
async def run_ragas_evaluation_deprecated(admin: dict = Depends(require_admin)):
    """已废弃：请使用 POST /evaluate/run"""
    logger.warning("POST /evaluate/ragas 已废弃，请使用 POST /evaluate/run")
    return await run_evaluation(request=None, admin=admin)
```

- [ ] **Step 3: Verify imports**

Run: `python -c "from api.admin_routes import admin_router; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add api/admin_routes.py
git commit -m "refactor: update admin API to use UnifiedEvaluator, deprecate ragas endpoints"
```

---

### Task 10: 端到端验证

- [ ] **Step 1: 验证所有模块可导入**

```bash
cd d:\EduRAG智慧问答系统
python -c "from evaluation.metrics import *; print('metrics OK')"
python -c "from evaluation.unified_evaluator import UnifiedEvaluator; print('unified_evaluator OK')"
python -c "from evaluation.report import format_report_html; print('report OK')"
python -c "from evaluation.evaluator import RAGEvaluator; print('evaluator compat OK')"
```

- [ ] **Step 2: 验证检索指标计算**

```bash
python -c "
from evaluation.metrics.retrieval import calc_retrieval_metrics
m = calc_retrieval_metrics(
    retrieved_doc_ids=['a','b','c','d','e'],
    retrieved_contents=['content a','content b','content c','content d','content e'],
    relevant_doc_ids=['a','c'],
    top_k=5
)
print(f'Precision={m.precision:.4f} Recall={m.recall:.4f} F1={m.f1_score:.4f} MRR={m.mrr:.4f}')
assert m.precision == 0.4, f'Expected 0.4, got {m.precision}'
assert m.mrr == 1.0, f'Expected 1.0, got {m.mrr}'
print('Retrieval metrics OK')
"
```

- [ ] **Step 3: 验证生成指标计算**

```bash
python -c "
from evaluation.metrics.generation import calc_bleu, calc_rouge_l, calc_keyword_match_rate
bleu = calc_bleu('勾股定理是直角三角形的重要性质', '勾股定理是直角三角形中斜边平方等于两直角边平方和的性质')
print(f'BLEU-1={bleu[\"bleu_1\"]:.4f}')
rouge = calc_rouge_l('勾股定理描述了直角三角形三边关系', '勾股定理是关于直角三角形三边关系的重要定理')
print(f'ROUGE-L={rouge:.4f}')
kw = calc_keyword_match_rate('勾股定理描述了直角三角形三边关系', ['勾股定理', '直角三角形', '三边关系'])
print(f'KeywordMatch={kw:.4f}')
assert kw > 0.5, f'Expected >0.5, got {kw}'
print('Generation metrics OK')
"
```

- [ ] **Step 4: 验证 LLM 评判指标**

```bash
python -c "
import asyncio
async def test():
    from evaluation.metrics.llm_judge import calc_answer_relevancy
    score = await calc_answer_relevancy(
        question='什么是勾股定理',
        answer='勾股定理是直角三角形中斜边平方等于两直角边平方和',
    )
    print(f'AnswerRelevancy={score:.4f}')
    assert 0 <= score <= 1, f'Expected 0-1, got {score}'
    print('LLM judge OK')
asyncio.run(test())
"
```

- [ ] **Step 5: 验证 unified_evaluator 完整流程**

```bash
python -c "
import asyncio
async def test():
    from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig
    
    def mock_query(query):
        from types import SimpleNamespace
        return SimpleNamespace(answer='测试答案', sources=[])
    
    evaluator = UnifiedEvaluator(EvalConfig(use_llm_judge=False, max_samples=2))
    report = await evaluator.evaluate([
        {'question': '测试问题1', 'expected_answer': '期望答案1', 'expected_keywords': ['测试']},
        {'question': '测试问题2', 'expected_answer': '期望答案2', 'expected_keywords': ['测试']},
    ], mock_query)
    
    print(f'样本数: {report.sample_count}')
    print(f'检索Precision: {report.avg_metrics[\"retrieval\"][\"precision\"]}')
    print(f'生成BLEU-1: {report.avg_metrics[\"generation\"][\"bleu_1\"]}')
    print(f'平均分: {report.avg_metrics[\"avg_score\"]}')
    print('UnifiedEvaluator OK')
asyncio.run(test())
"
```

- [ ] **Step 6: Commit**

```bash
git commit -m "test: verify unified evaluator end-to-end"
```

---

## Self-Review Checklist

1. **Spec coverage**: 每个 spec 需求都有对应 task — 检索指标(T2)、生成指标(T3)、LLM 评判(T4)、报告(T5)、统一入口(T6)、兼容包装(T7)、删除 ragas(T8)、API 更新(T9)、验证(T10)
2. **Placeholder scan**: 无 TBD/TODO/占位符
3. **Type consistency**: `SampleScore`, `EvalReport`, `RetrievalMetrics`, `GenerationMetrics`, `RAGQualityMetrics` 在所有 task 中签名一致
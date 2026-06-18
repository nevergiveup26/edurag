# 统一评估器设计规格

**日期**: 2026-06-18
**状态**: 已批准
**目标**: 合并 `evaluator.py` 和 `ragas_evaluator.py` 为统一评估器，去掉 ragas 库依赖，混合模式实现 LLM 评判指标

---

## 1. 背景与动机

当前 `evaluation/` 目录存在两个独立的评估器：
- `evaluator.py`（575行）：检索指标（Precision/Recall/F1/MRR/NDCG）+ 生成指标（BLEU/ROUGE/关键词匹配率）
- `ragas_evaluator.py`（575行）：RAGAS 指标（Faithfulness/AnswerRelevancy/ContextRelevancy 等），强依赖 ragas 库

问题：
1. 功能重叠，两套查询采集逻辑，指标互不打通
2. ragas 库依赖大量 monkey-patch（qwen-max `✿RETURN✿` 清洗、instructor Mode.TOOLS、AsyncOpenAI 包装），版本升级即崩溃
3. admin API 两套平行端点（`/evaluate/ragas`, `/evaluate/ragas/stream` 与 `/evaluate/run`）
4. HTML 报告简陋，无图表

## 2. 文件结构

```
evaluation/
├── unified_evaluator.py    ← 新：统一评估器（合并 evaluator.py + ragas_evaluator.py）
├── metrics/
│   ├── __init__.py
│   ├── retrieval.py        ← 检索指标：Precision/Recall/F1/MRR/NDCG/HitRate + ContextPrecision(embedding)
│   ├── generation.py       ← 生成指标：BLEU/ROUGE-L/关键词匹配率
│   └── llm_judge.py        ← LLM评判：Faithfulness(分解) + AnswerRelevancy(prompt直出) + Correctness
├── report.py               ← HTML报告生成（含 matplotlib 图表）
├── evaluator.py            ← 保留但标记废弃，内部转调 unified_evaluator
├── ragas_evaluator.py      ← 删除
├── ablation.py             ← 保持不变，query_func 改为对接统一评估器
└── run_retrieval_eval.py   ← 保持不变
```

## 3. 指标全景

| 类别 | 指标 | 计算方式 | 需要 ground_truth |
|------|------|---------|-------------------|
| 检索 | Precision@K, Recall@K, F1, MRR, NDCG, HitRate | doc_id 匹配 / 关键词匹配 | 需要 relevant_doc_ids 或 keywords |
| 检索 | ContextPrecision | embedding 相似度 (query vs each context) 均值 | 否 |
| 检索 | ContextRecall | 无 ground_truth 时不可计算，标记 N/A | 是 |
| 生成 | BLEU-1/2, ROUGE-L | 文本计算 (jieba 分词) | 需要 expected_answer |
| 生成 | 关键词匹配率 | 关键词命中/总关键词 | 需要 expected_keywords |
| RAG质量 | Faithfulness (忠实度) | **分解评分**: LLM 拆 claims → 逐条验证 → 支持率 | 否 |
| RAG质量 | AnswerRelevancy (答案相关性) | **Prompt 直出**: LLM 直接打 0-1 分 | 否 |
| RAG质量 | ContextRelevancy (上下文相关性) | embedding 相似度 (query vs context) | 否 |
| RAG质量 | AnswerCorrectness (正确性) | Prompt 直出 (与 ground_truth 对比) | 需要 ground_truth |

### 3.1 LLM 评判指标详解

**Faithfulness（分解评分）**：
1. Claim 拆解：LLM 将 answer 拆分为 N 条独立事实陈述
2. 逐条验证：对每条 claim，LLM 判断是否被 contexts 中的信息支持（是/否）
3. 得分 = 被支持的 claims 数 / 总 claims 数
4. LLM 调用次数：2 次（拆解 1 次 + 批量验证 1 次，所有 claims 打包一次请求）

**AnswerRelevancy（Prompt 直出）**：
- 单次 LLM 调用，输入 question + answer，输出 0-1 分数
- Prompt 评估维度：是否直接回应问题、是否跑题、是否有冗余信息

**AnswerCorrectness（Prompt 直出）**：
- 单次 LLM 调用，输入 question + answer + ground_truth，输出 0-1 分数
- 仅在 ground_truth 存在时计算

**ContextPrecision / ContextRelevancy（embedding 计算）**：
- 用项目已有的 text-embedding-v4 计算 query 与每个 context 的余弦相似度
- ContextPrecision = mean(相似度)，ContextRelevancy = mean(相似度)
- 零 LLM 调用，纯向量计算

## 4. 核心类设计

```python
@dataclass
class EvalConfig:
    metrics: List[str]           # 要计算的指标列表
    llm_model: str = "qwen-turbo"  # LLM 评判用模型（轻量）
    top_k: int = 5
    parallel_queries: int = 8    # 查询并发数
    parallel_scoring: int = 4    # 指标计算并发数
    use_llm_judge: bool = True   # 是否启用 LLM 评判

@dataclass
class SampleScore:
    """单样本全部指标得分"""
    retrieval: RetrievalMetrics
    generation: GenerationMetrics
    rag_quality: RAGQualityMetrics
    execution_time: float

@dataclass
class EvalReport:
    """完整评估报告"""
    config: EvalConfig
    sample_count: int
    total_time: float
    avg_metrics: SampleScore     # 平均指标
    sample_scores: List[SampleScore]
    charts: Dict[str, str]       # base64 图表

class UnifiedEvaluator:
    def __init__(self, config: EvalConfig = None):
        self.config = config or EvalConfig()
        self._llm = None          # 延迟加载 get_fast_llm()
        self._embedder = None     # 延迟加载 VectorRetriever 的 embedding

    # 同步入口
    async def evaluate(self, test_cases: List[dict], query_func) -> EvalReport:
        """阶段一：并行采集 → 阶段二：批量计算指标 → 返回报告"""

    # 流式入口
    async def evaluate_stream(self, test_cases, query_func,
                              cancel_event=None) -> AsyncGenerator:
        """逐样本采集+计算 → 实时 yield SSE 事件"""

    # 内部
    async def _collect_samples(self, test_cases, query_func,
                               cancel_event=None) -> List[dict]:
        """并行查询，收集 answers + contexts"""

    async def _score_sample(self, sample: dict) -> SampleScore:
        """并行计算一个样本的全部指标"""

    async def _compute_llm_metrics(self, samples) -> Dict[str, float]:
        """批量 LLM 评判（Faithfulness + AnswerRelevancy）"""

    def format_report(self, report: EvalReport) -> str:
        """生成 HTML 报告"""
```

## 5. 数据流

### 5.1 evaluate() 同步流程

```
test_cases (N条)
    │
    ▼
[并行查询采集] ─── parallel_queries=8
    │
    ▼
samples (answers + contexts)
    │
    ├──→ [检索指标计算] ─── 纯计算，无 LLM
    ├──→ [生成指标计算] ─── BLEU/ROUGE，无 LLM
    └──→ [LLM 评判] ─── parallel_scoring=4
              ├── Faithfulness (分解评分)
              ├── AnswerRelevancy (prompt 直出)
              └── AnswerCorrectness (prompt 直出, 如有 ground_truth)
    │
    ▼
EvalReport → format_report() → HTML
```

### 5.2 evaluate_stream() 流式流程

```
for each test_case:
    yield {"event": "progress", "current": i, "total": N}
    query → sample → _score_sample()
    yield {"event": "sample_done", "index": i, "score": {...}, "cumulative": {...}}
yield {"event": "complete", "report": {...}}
```

### 5.3 Faithfulness 分解评分流程

```
answer ──→ LLM拆解 ──→ [claim_1, claim_2, ..., claim_n]
                              │
                              ▼
              LLM逐条验证 ←── contexts
              (一次批量请求)
                              │
                              ▼
              supported_count / total_count = Faithfulness
```

## 6. API 变更

### admin_routes.py 变更

| 旧端点 | 变更 |
|--------|------|
| `POST /evaluate/run` | 保留，内部改为调用 `UnifiedEvaluator.evaluate()` |
| `POST /evaluate/ragas` | 废弃，合并到 `/evaluate/run` |
| `GET /evaluate/ragas/stream` | 废弃，合并到 `/evaluate/stream` |
| `GET /evaluate/ragas/samples` | 保留，路径改为 `/evaluate/samples` |
| `GET /evaluate/stream` | 新增：流式评测（SSE），替代 ragas 流式端点 |

### 新请求参数

```json
{
  "test_cases": [...],
  "metrics": ["retrieval", "generation", "faithfulness", "answer_relevancy"],
  "max_samples": 100,
  "parallel_queries": 8,
  "parallel_scoring": 4
}
```

## 7. 报告输出

统一 HTML 报告，分四个区域：
- **顶部概览卡片**：样本数、总耗时、综合平均分
- **检索指标区**：柱状图（Precision/Recall/F1/MRR/NDCG/HitRate）+ ContextPrecision 进度条
- **生成 & RAG 质量区**：BLEU/ROUGE 对比图 + Faithfulness/AnswerRelevancy/Correctness 进度条
- **样本详情表**：可折叠的逐样本明细表

## 8. 兼容性

- `evaluator.py` 保留为兼容包装，内部转调 `UnifiedEvaluator`，已有调用方（`ablation.py`, `admin_routes.py` 的非 ragas 部分）无需立即修改
- `ragas_evaluator.py` 删除，`admin_routes.py` 中 ragas 端点改为调用 `UnifiedEvaluator`
- `ablation.py` 的 `_build_query_func` 无需修改，它只依赖 query_func 接口

## 9. 不涉及范围

- 测试集构建（`build_k12_test_set.py`、`cmrc_evaluator.py`）保持不变
- 消融实验（`ablation.py`）保持不变
- 纯检索评测（`run_retrieval_eval.py`）保持不变
- 前端 UI 改动不在此次范围
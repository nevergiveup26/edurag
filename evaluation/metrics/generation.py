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
    llm_score: float = -1.0


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
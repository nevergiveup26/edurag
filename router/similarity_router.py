"""
Layer 2: 相似度路由
基于向量相似度匹配预设锚点示例库
预期命中率 ~30%（累计 90%），延迟 ~50ms
"""
import numpy as np
from typing import Optional, List

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
                    f"score={best_score:.3f}"
                )
                return strategy

            logger.debug(f"[SimilarityRouter] 未命中: best_score={best_score:.3f} < {self.threshold}")
            return None
        except Exception as e:
            logger.warning(f"[SimilarityRouter] 异常，跳过 Layer 2: {e}")
            return None
"""
在线评估模块 — 用户反馈收集与质量监控

提供：
1. 用户反馈收集 API（评分 + 评论）
2. 反馈数据持久化（MySQL feedback 表）
3. 质量指标聚合（按策略/知识库/时间维度）
4. 反馈驱动检索优化（高分结果提升权重）

用法:
    eval_tracker = EvaluationTracker()
    eval_tracker.record_feedback(query_id, rating=4, comment="回答准确")
    metrics = eval_tracker.get_quality_metrics(kb_id="kb_001", days=7)
"""
import uuid
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from core.logger import get_logger

logger = get_logger("evaluation")


class EvaluationTracker:
    """在线评估追踪器 — 管理用户反馈和质量指标"""

    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        if self._db is None:
            from database.mysql_db import MySQLDB
            self._db = MySQLDB()
        return self._db

    def init_tables(self):
        """初始化反馈相关表"""
        sql = """
        CREATE TABLE IF NOT EXISTS query_feedback (
            id VARCHAR(64) PRIMARY KEY,
            query_id VARCHAR(64) NOT NULL,
            conversation_id VARCHAR(64),
            kb_id VARCHAR(64),
            user_id VARCHAR(64),
            query TEXT,
            answer TEXT,
            rating INT CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            strategy_used VARCHAR(50),
            router_used VARCHAR(50),
            response_time_ms INT,
            metadata JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_query_id (query_id),
            INDEX idx_kb_id (kb_id),
            INDEX idx_rating (rating),
            INDEX idx_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        try:
            for s in sql.split(';'):
                s = s.strip()
                if s:
                    self.db.execute(s)
            logger.info("反馈表初始化完成")
        except Exception as e:
            logger.error(f"反馈表初始化失败: {e}")

    # ─── 记录反馈 ───

    def record_feedback(self, query_id: str, rating: int = None,
                        comment: str = "", query: str = "", answer: str = "",
                        conversation_id: str = "", kb_id: str = "",
                        user_id: str = "", strategy_used: str = "",
                        router_used: str = "", response_time_ms: int = 0,
                        metadata: dict = None) -> str:
        """
        记录一条用户反馈

        Returns:
            反馈ID
        """
        feedback_id = str(uuid.uuid4())
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        sql = """INSERT INTO query_feedback
                 (id, query_id, conversation_id, kb_id, user_id, query, answer,
                  rating, comment, strategy_used, router_used, response_time_ms, metadata)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        try:
            self.db.execute(sql, (
                feedback_id, query_id, conversation_id, kb_id, user_id,
                query[:500], answer[:2000], rating, comment[:500],
                strategy_used, router_used, response_time_ms, meta_json,
            ))
            logger.info(f"反馈已记录: id={feedback_id}, rating={rating}")
            return feedback_id
        except Exception as e:
            logger.error(f"记录反馈失败: {e}")
            return ""

    # ─── 查询反馈 ───

    def get_feedback(self, query_id: str = None, conversation_id: str = None,
                     kb_id: str = None, limit: int = 50) -> List[dict]:
        """查询历史反馈"""
        conditions = []
        params = []
        if query_id:
            conditions.append("query_id = %s")
            params.append(query_id)
        if conversation_id:
            conditions.append("conversation_id = %s")
            params.append(conversation_id)
        if kb_id:
            conditions.append("kb_id = %s")
            params.append(kb_id)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM query_feedback {where} ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        rows = self.db.query(sql, tuple(params))
        return [self._row_to_dict(r) for r in rows]

    # ─── 质量指标 ───

    def get_quality_metrics(self, kb_id: str = None, days: int = 7) -> dict:
        """
        获取质量指标汇总

        Returns:
            {
                "total_feedback": 120,
                "avg_rating": 3.8,
                "rating_distribution": {1: 3, 2: 8, 3: 20, 4: 45, 5: 44},
                "daily_trend": [{"date": "2026-06-01", "avg_rating": 3.9, "count": 15}, ...],
                "strategy_metrics": {"direct": 4.1, "hyde": 3.5},
                "good_rate": 0.74,  # 4-5星占比
                "bad_rate": 0.09,   # 1-2星占比
            }
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        conditions = ["created_at >= %s"]
        params = [since]
        if kb_id:
            conditions.append("kb_id = %s")
            params.append(kb_id)

        where = "WHERE " + " AND ".join(conditions)

        # 总览统计
        total_row = self.db.query_one(
            f"SELECT COUNT(*) as total, AVG(rating) as avg_rating FROM query_feedback {where}",
            tuple(params)
        )
        total = total_row.get("total", 0) if total_row else 0
        avg_rating = round(total_row.get("avg_rating", 0) or 0, 2) if total_row else 0

        # 评分分布
        dist_rows = self.db.query(
            f"SELECT rating, COUNT(*) as cnt FROM query_feedback {where} GROUP BY rating ORDER BY rating",
            tuple(params)
        )
        rating_dist = {int(r["rating"]): r["cnt"] for r in dist_rows}

        # 每日趋势
        trend_rows = self.db.query(
            f"SELECT DATE(created_at) as date, AVG(rating) as avg_r, COUNT(*) as cnt "
            f"FROM query_feedback {where} GROUP BY DATE(created_at) ORDER BY date",
            tuple(params)
        )
        daily_trend = [
            {"date": str(r["date"]), "avg_rating": round(float(r["avg_r"] or 0), 2),
             "count": r["cnt"]}
            for r in trend_rows
        ]

        # 策略维度
        strategy_rows = self.db.query(
            f"SELECT strategy_used, AVG(rating) as avg_r, COUNT(*) as cnt "
            f"FROM query_feedback {where} AND strategy_used != '' GROUP BY strategy_used",
            tuple(params)
        )
        strategy_metrics = {
            r["strategy_used"]: round(float(r["avg_r"] or 0), 2)
            for r in strategy_rows if r["strategy_used"]
        }

        # 好评率/差评率
        good = rating_dist.get(4, 0) + rating_dist.get(5, 0)
        bad = rating_dist.get(1, 0) + rating_dist.get(2, 0)

        return {
            "total_feedback": total,
            "avg_rating": avg_rating,
            "rating_distribution": rating_dist,
            "daily_trend": daily_trend,
            "strategy_metrics": strategy_metrics,
            "good_rate": round(good / max(total, 1), 2),
            "bad_rate": round(bad / max(total, 1), 2),
            "period_days": days,
        }

    # ─── 内部 ───

    def _row_to_dict(self, row: dict) -> dict:
        meta = {}
        if row.get("metadata"):
            try:
                meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "id": row.get("id"),
            "query_id": row.get("query_id"),
            "conversation_id": row.get("conversation_id"),
            "kb_id": row.get("kb_id"),
            "query": row.get("query"),
            "answer": row.get("answer", "")[:300],
            "rating": row.get("rating"),
            "comment": row.get("comment"),
            "strategy_used": row.get("strategy_used"),
            "router_used": row.get("router_used"),
            "response_time_ms": row.get("response_time_ms"),
            "created_at": str(row.get("created_at", "")),
            "metadata": meta,
        }


# ========== 反馈驱动的结果重排序 ==========

class FeedbackReranker:
    """
    基于历史反馈的智能重排序

    高分评价过的 chunk 权重上升，低分的下降。
    使用 jieba 分词 + Jaccard 相似度做语义匹配（替代原始空白符分词）。
    """

    def __init__(self, tracker: EvaluationTracker = None):
        self.tracker = tracker or EvaluationTracker()
        self._jieba_available = None

    def _ensure_jieba(self) -> bool:
        if self._jieba_available is None:
            try:
                import jieba
                jieba.lcut("测试")  # warm-up
                self._jieba_available = True
            except ImportError:
                self._jieba_available = False
        return self._jieba_available

    @staticmethod
    def _tokenize(text: str) -> set:
        """分词并返回 token 集合"""
        try:
            import jieba
            tokens = jieba.lcut(text.lower().strip())
        except ImportError:
            tokens = text.lower().strip().split()
        # 过滤单字和空白
        return {t for t in tokens if len(t.strip()) > 1}

    @staticmethod
    def _jaccard(set_a: set, set_b: set) -> float:
        """计算两个集合的 Jaccard 相似度"""
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def boost_by_feedback(self, results: list, kb_id: str = None,
                           recent_days: int = 30) -> list:
        """
        根据历史反馈调整检索结果的权重

        使用 jieba 分词 + Jaccard 相似度匹配反馈查询与 chunk 内容，
        高分查询匹配的 chunk 权重提升，低分的权重降低。
        调整幅度与相似度成正比，避免二值化 ±15%。

        Returns:
            调整后的结果列表
        """
        if not results:
            return results

        try:
            self._ensure_jieba()

            since = (datetime.now() - timedelta(days=recent_days)).strftime("%Y-%m-%d")
            conditions = ["created_at >= %s", "rating IS NOT NULL"]
            params = [since]
            if kb_id:
                conditions.append("kb_id = %s")
                params.append(kb_id)

            where = "WHERE " + " AND ".join(conditions)
            rows = self.tracker.db.query(
                f"SELECT query, rating FROM query_feedback {where}",
                tuple(params)
            )

            # 构建 (查询文本, 分词集合, 评分) 元组列表
            high_feedbacks = []
            low_feedbacks = []
            for r in rows:
                query = r.get("query", "")
                rating = r.get("rating", 3)
                if not query:
                    continue
                tokens = self._tokenize(query)
                if rating >= 4 and tokens:
                    high_feedbacks.append((query, tokens, rating))
                elif rating <= 2 and tokens:
                    low_feedbacks.append((query, tokens, rating))

            # 限制数量避免过多计算
            high_feedbacks = high_feedbacks[:30]
            low_feedbacks = low_feedbacks[:15]

            # 对每个检索结果计算相似度并调整权重
            for result in results:
                content = result.chunk.content if hasattr(result, 'chunk') else str(result)
                content_tokens = self._tokenize(content)
                if not content_tokens:
                    continue

                # 高分查询相似度 → 提升权重
                max_high_sim = 0.0
                for _, fb_tokens, _ in high_feedbacks:
                    sim = self._jaccard(content_tokens, fb_tokens)
                    if sim > max_high_sim:
                        max_high_sim = sim

                if max_high_sim > 0.05:  # 最低相似度阈值
                    # 提升幅度与相似度成正比，上限 20%
                    boost = 1.0 + min(max_high_sim * 2.0, 0.20)
                    result.score *= boost

                # 低分查询相似度 → 降低权重
                max_low_sim = 0.0
                for _, fb_tokens, _ in low_feedbacks:
                    sim = self._jaccard(content_tokens, fb_tokens)
                    if sim > max_low_sim:
                        max_low_sim = sim

                if max_low_sim > 0.05:
                    # 降低幅度与相似度成正比，下限 15%
                    penalty = 1.0 - min(max_low_sim * 2.0, 0.15)
                    result.score *= penalty

            results.sort(key=lambda x: x.score, reverse=True)

        except Exception as e:
            logger.warning(f"反馈重排序失败: {e}")

        return results
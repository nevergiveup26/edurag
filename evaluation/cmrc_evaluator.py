"""
CMRC 2018 检索评测模块

将 CMRC 2018 数据集（SQuAD 格式）入库到 Milvus/MySQL/chunk_store，
然后对每个 question 检索 top-k 文档，通过命中 correct context 评估检索质量。

指标：Precision@k, Recall@k, F1, MRR, NDCG, Hit Rate（复用 RAGEvaluator）
可选：生成评测（LLM 生成答案 → CMRC 官方 EM/F1 评分）

用法：
    evaluator = CMRCEvaluator()
    doc_ids, chunk_count = evaluator.index_data("cmrc2018/squad-style-data/cmrc2018_dev.json")
    samples = evaluator.build_samples()
    report = evaluator.run_retrieval_eval(samples, query_func)
    evaluator.cleanup()
"""
import json
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from core.logger import get_logger

logger = get_logger("cmrc_evaluator")

# CMRC doc_id 前缀，用于批量清理
CMRC_DOC_PREFIX = "cmrc_"


class CMRCEvaluator:
    """CMRC 2018 数据集评测器"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent / "cmrc2018" / "squad-style-data")
        self.data_dir = Path(data_dir)
        self._loaded_entries: List[Dict] = []
        self._cmrc_doc_ids: List[str] = []

    # ======================== 数据加载 ========================

    def load_data(self, split: str = "dev") -> List[Dict]:
        """
        加载 CMRC SQuAD 格式数据，扁平化为 entries 列表。

        Returns:
            [{"context_id": "DEV_0", "context": "...",
              "qas": [{"query_id": "...", "question": "...", "answers": ["..."]}]}]
        """
        file_path = self.data_dir / f"cmrc2018_{split}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"CMRC 数据文件不存在: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries = []
        for doc in data.get("data", []):
            for para in doc.get("paragraphs", []):
                entry = {
                    "context_id": para["id"],
                    "context": para["context"],
                    "qas": [],
                }
                for qa in para.get("qas", []):
                    answers = [a["text"] for a in qa.get("answers", [])]
                    # 去重
                    unique_answers = list(dict.fromkeys(answers))
                    entry["qas"].append({
                        "query_id": qa["id"],
                        "question": qa["question"],
                        "answers": unique_answers,
                    })
                entries.append(entry)

        self._loaded_entries = entries
        logger.info(f"CMRC {split} 加载完成: {len(entries)} 篇 context, "
                    f"{sum(len(e['qas']) for e in entries)} 个 QA 对")
        return entries

    # ======================== 入库索引 ========================

    def index_data(self, split: str = "dev", chunk_size: int = 800) -> Tuple[List[str], int]:
        """
        将 CMRC 数据入库：split → chunks → vectorize → MySQL + Milvus + chunk_store

        Returns:
            (doc_ids, chunk_count)
        """
        if not self._loaded_entries:
            self.load_data(split)

        from data_processor.document_splitter import DocumentSplitter
        from data_processor.vectorizer import Vectorizer
        from database.mysql_db import MySQLDB
        from database.milvus_db import MilvusDB
        from database.chunk_store import save_chunks
        from core.models import Document, DocumentChunk

        splitter = DocumentSplitter(chunk_size=chunk_size, chunk_overlap=80, mode="semantic")
        vectorizer = Vectorizer()
        mysql_db = MySQLDB()
        milvus_db = MilvusDB()

        # 确保 Milvus collection 存在
        milvus_db.connect()
        milvus_db.create_collection()

        doc_ids = []
        total_chunks = 0
        all_chunks = []

        for entry in self._loaded_entries:
            context_id = entry["context_id"]
            doc_id = f"{CMRC_DOC_PREFIX}{context_id}"

            # 创建文档
            doc = Document(
                doc_id=doc_id,
                title=context_id,
                source="cmrc2018",
                content=entry["context"],
                metadata={"dataset": "cmrc2018", "split": split},
            )

            # 切分
            chunks = splitter.split(doc)
            if not chunks:
                chunks = [DocumentChunk(
                    chunk_id=f"{doc_id}_chunk_0",
                    doc_id=doc_id,
                    content=entry["context"],
                    metadata={"dataset": "cmrc2018", "split": split},
                )]

            # 向量化
            chunks = vectorizer.embed_documents(chunks)

            # MySQL
            mysql_db.insert_document(
                doc_id=doc_id,
                title=context_id,
                source="cmrc2018",
                content=entry["context"],
                metadata={"dataset": "cmrc2018", "split": split},
            )

            # Milvus
            try:
                milvus_db.insert_vectors(
                    ids=[c.chunk_id for c in chunks],
                    embeddings=[c.embedding for c in chunks],
                    contents=[c.content for c in chunks],
                    doc_ids=[doc_id for _ in chunks],
                    metadatas=[c.metadata for c in chunks],
                )
            except Exception as e:
                logger.warning(f"Milvus 插入失败（使用本地模式继续）: {e}")

            all_chunks.extend(chunks)
            doc_ids.append(doc_id)
            total_chunks += len(chunks)

        # 持久化到 chunk_store
        save_chunks(all_chunks)

        # 使缓存失效，下次查询重建索引
        try:
            from api.student_routes import invalidate_retriever_cache
            invalidate_retriever_cache()
        except Exception as e:
            logger.debug(f"检索器缓存失效失败（非关键）: {e}")

        self._cmrc_doc_ids = doc_ids
        logger.info(f"CMRC 入库完成: {len(doc_ids)} 篇文档 → {total_chunks} 个片段")
        return doc_ids, total_chunks

    # ======================== 构建评估样本 ========================

    def build_samples(self) -> List:
        """
        为每个 QA 对构建 EvalSample。

        relevant_doc_ids 指向包含该答案的 context（cmrc_前缀），
        检索评估通过判断检索结果的 doc_id 是否在 relevant_doc_ids 中来计算精度/召回。
        """
        from evaluation.evaluator import EvalSample

        if not self._loaded_entries:
            raise RuntimeError("请先调用 load_data() 加载数据")

        samples = []
        for entry in self._loaded_entries:
            doc_id = f"{CMRC_DOC_PREFIX}{entry['context_id']}"
            for qa in entry["qas"]:
                answers = qa["answers"]
                samples.append(EvalSample(
                    query=qa["question"],
                    expected_answer=answers[0] if answers else "",
                    expected_keywords=[],
                    relevant_doc_ids=[doc_id],
                    category="cmrc2018",
                ))

        logger.info(f"构建 {len(samples)} 个评估样本")
        return samples

    # ======================== 检索评测 ========================

    def run_retrieval_eval(self, samples: List = None, query_func=None) -> Dict:
        """
        运行检索评测。

        Args:
            samples: EvalSample 列表（不传则从已加载数据构建）
            query_func: (query: str) -> 含 .answer 和 .sources 的可调用对象

        Returns:
            含 retrieval 指标、sample_count、total_time 的字典
        """
        import time as _time
        from evaluation.evaluator import RAGEvaluator

        if samples is None:
            samples = self.build_samples()

        if query_func is None:
            from api.admin_routes import _make_query_func
            query_func = _make_query_func()
            logger.info("使用 _make_query_func() 作为默认 query_func")

        evaluator = RAGEvaluator()
        evaluator.samples = samples

        t0 = _time.time()
        report = evaluator.run_full_evaluation(query_func)
        elapsed = _time.time() - t0

        result = {
            "retrieval": {
                "precision": round(report.retrieval.precision, 4),
                "recall": round(report.retrieval.recall, 4),
                "f1_score": round(report.retrieval.f1_score, 4),
                "mrr": round(report.retrieval.mrr, 4),
                "ndcg": round(report.retrieval.ndcg, 4),
                "hit_rate": round(report.retrieval.hit_rate, 4),
            },
            "sample_count": report.sample_count,
            "total_time": round(elapsed, 2),
            "charts": report.charts,
        }
        logger.info(f"CMRC 检索评测完成: {result['retrieval']}")
        return result

    # ======================== 生成评测（含 CMRC 官方 F1/EM）=======================

    def run_generation_eval(self, samples: List = None, query_func=None) -> Dict:
        """
        运行生成评测：LLM 生成答案 → CMRC 官方 F1/EM 评分。

        使用 cmrc2018/squad-style-data/cmrc2018_evaluate.py 的官方评分逻辑。
        """
        import time as _time
        import sys
        sys.path.insert(0, str(self.data_dir))

        if samples is None:
            samples = self.build_samples()

        if query_func is None:
            from api.admin_routes import _make_query_func
            query_func = _make_query_func()
            logger.info("使用 _make_query_func() 作为默认 query_func")

        # 构建预测文件
        predictions = {}
        t0 = _time.time()
        for i, sample in enumerate(samples):
            resp = query_func(sample.query)
            predictions[sample.query] = resp.answer if hasattr(resp, 'answer') else str(resp)
            if (i + 1) % 500 == 0:
                logger.info(f"生成评测进度: {i+1}/{len(samples)}")

        # 构建 ground truth（CMRC 原格式：[{context_id, context_text, qas: [{query_id, query_text, answers}]}]）
        ground_truth = []
        for entry in self._loaded_entries:
            gt_entry = {
                "context_id": entry["context_id"],
                "context_text": entry["context"],
                "qas": [],
            }
            for qa in entry["qas"]:
                gt_entry["qas"].append({
                    "query_id": qa["query_id"],
                    "query_text": qa["question"],
                    "answers": qa["answers"],
                })
            ground_truth.append(gt_entry)

        # 需要 query_id → prediction 的映射
        pred_by_id = {}
        for entry in self._loaded_entries:
            for qa in entry["qas"]:
                answer = predictions.get(qa["question"], "")
                pred_by_id[qa["query_id"]] = answer

        # 调用 Py3 适配版 CMRC evaluate（需 SQuAD 格式：{"data": [{"paragraphs": [...]}]}）
        from evaluation.cmrc2018_evaluate import evaluate as cmrc_evaluate
        f1, em, total, skip = cmrc_evaluate(
            {"data": [{"paragraphs": ground_truth}]}, pred_by_id
        )
        avg = (f1 + em) * 0.5

        elapsed = _time.time() - t0
        result = {
            "cmrc_official": {
                "average": round(avg, 3),
                "f1": round(f1, 3),
                "em": round(em, 3),
                "total": total,
                "skip": skip,
            },
            "sample_count": len(samples),
            "total_time": round(elapsed, 2),
        }
        logger.info(f"CMRC 生成评测完成: {result['cmrc_official']}")
        return result

    # ======================== 清理 ========================

    def cleanup(self):
        """删除所有 CMRC 评测数据（MySQL + Milvus + chunk_store）"""
        if not self._cmrc_doc_ids:
            logger.info("无 CMRC 数据需要清理")
            return

        from database.mysql_db import MySQLDB
        from database.milvus_db import MilvusDB
        from database.chunk_store import remove_chunks_by_doc_id

        mysql_db = MySQLDB()
        milvus_db = MilvusDB()

        removed = 0
        for doc_id in self._cmrc_doc_ids:
            try:
                mysql_db.delete_document(doc_id)
            except Exception as e:
                logger.debug(f"MySQL 删除失败: {e}")
            try:
                milvus_db.delete_by_doc_id(doc_id)
            except Exception as e:
                logger.debug(f"Milvus 删除失败: {e}")
            try:
                remove_chunks_by_doc_id(doc_id)
            except Exception as e:
                logger.debug(f"chunk_store 删除失败: {e}")
            removed += 1

        logger.info(f"CMRC 数据已清理: {removed} 个文档")
        self._cmrc_doc_ids = []
        self._loaded_entries = []


def load_and_index_all_splits(data_dir: str = None):
    """加载并入库 CMRC 全部三个 split（dev + train + trial）"""
    evaluator = CMRCEvaluator(data_dir)
    all_doc_ids = []
    total_chunks = 0
    for split in ["dev", "train", "trial"]:
        evaluator.load_data(split)
        doc_ids, chunks = evaluator.index_data(split)
        all_doc_ids.extend(doc_ids)
        total_chunks += chunks
    return all_doc_ids, total_chunks

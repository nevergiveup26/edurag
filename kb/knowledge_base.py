"""
知识库管理模块
支持多知识库的创建、编辑、删除、搜索、统计等管理操作

特性：
- 多知识库隔离：不同知识库存放独立文档集合
- CRUD全生命周期管理
- 文档与知识库关联（多对多）
- 全文搜索与过滤器
- 统计信息（文档数/片段数/向量数）
"""
import uuid
import json
import os
from typing import List, Dict, Optional, Any
from datetime import datetime

from core.logger import get_logger
from database.mysql_db import MySQLDB

logger = get_logger("knowledge_base")


class KnowledgeBase:
    """知识库实体"""
    def __init__(self, kb_id: str = None, name: str = "", description: str = "",
                 category: str = "通用", tags: List[str] = None,
                 doc_count: int = 0, chunk_count: int = 0, total_size: int = 0,
                 created_at: str = None, updated_at: str = None):
        self.kb_id = kb_id or str(uuid.uuid4())
        self.name = name
        self.description = description
        self.category = category
        self.tags = tags or []
        self.doc_count = doc_count
        self.chunk_count = chunk_count
        self.total_size = total_size
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.kb_id,
            "kb_id": self.kb_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "doc_count": self.doc_count,
            "chunk_count": self.chunk_count,
            "total_size": self.total_size,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class KnowledgeBaseManager:
    """知识库管理器 — 统一管理所有知识库"""

    def __init__(self):
        self._db: Optional[MySQLDB] = None

    @property
    def db(self) -> MySQLDB:
        if self._db is None:
            self._db = MySQLDB()
        return self._db

    def init_tables(self):
        """初始化知识库相关表（在 MySQLDB.init_tables 扩展）"""
        sql = """
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(100) DEFAULT '通用',
            tags JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS kb_documents (
            kb_id VARCHAR(64) NOT NULL,
            doc_id VARCHAR(64) NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (kb_id, doc_id),
            FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        try:
            for s in sql.split(';'):
                s = s.strip()
                if s:
                    self.db.execute(s)
            logger.info("知识库表初始化完成")
        except Exception as e:
            logger.error(f"知识库表初始化失败: {e}")

    # ======================== CRUD ========================

    def create(self, name: str, description: str = "",
               category: str = "通用", tags: List[str] = None) -> KnowledgeBase:
        """创建知识库"""
        kb_id = str(uuid.uuid4())
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        sql = """INSERT INTO knowledge_bases (id, name, description, category, tags)
                 VALUES (%s, %s, %s, %s, %s)"""
        self.db.execute(sql, (kb_id, name, description, category, tags_json))
        logger.info(f"知识库已创建: {name} ({kb_id})")
        return KnowledgeBase(kb_id=kb_id, name=name, description=description,
                             category=category, tags=tags or [])

    def get(self, kb_id: str) -> Optional[KnowledgeBase]:
        """获取单个知识库"""
        row = self.db.query_one("SELECT * FROM knowledge_bases WHERE id = %s", (kb_id,))
        if not row:
            return None
        return self._row_to_kb(row)

    def list(self, page: int = 1, page_size: int = 20,
             category: str = None, keyword: str = None) -> Dict:
        """列出知识库（支持分类筛选、关键词搜索）"""
        conditions = []
        params = []

        if category:
            conditions.append("category = %s")
            params.append(category)
        if keyword:
            conditions.append("(name LIKE %s OR description LIKE %s)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        offset = (page - 1) * page_size

        # 查询总数
        count_row = self.db.query_one(
            f"SELECT COUNT(*) as total FROM knowledge_bases {where}",
            tuple(params)
        )
        total = count_row.get("total", 0) if count_row else 0

        # 查询列表
        rows = self.db.query(
            f"SELECT * FROM knowledge_bases {where} ORDER BY updated_at DESC LIMIT %s OFFSET %s",
            tuple(params + [page_size, offset])
        )

        items = []
        for row in rows:
            kb = self._row_to_kb(row)
            cnt_row = self.db.query_one(
                "SELECT COUNT(*) as cnt FROM kb_documents WHERE kb_id = %s", (kb.kb_id,)
            )
            kb.doc_count = cnt_row.get("cnt", 0) if cnt_row else 0
            items.append(kb.to_dict())

        # 从轻量缓存文件读取 chunk_count（避免扫描大 JSONL）
        _inject_chunk_counts(items)

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def update(self, kb_id: str, name: str = None, description: str = None,
               category: str = None, tags: List[str] = None) -> bool:
        """更新知识库"""
        sets = []
        params = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if category is not None:
            sets.append("category = %s")
            params.append(category)
        if tags is not None:
            sets.append("tags = %s")
            params.append(json.dumps(tags, ensure_ascii=False))

        if not sets:
            return False

        params.append(kb_id)
        sql = f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = %s"
        self.db.execute(sql, tuple(params))
        logger.info(f"知识库已更新: {kb_id}")
        return True

    def delete(self, kb_id: str) -> bool:
        """删除知识库（级联删除关联文档，并清理孤立文档记录）"""
        self.db.delete_knowledge_base(kb_id)
        logger.info(f"知识库已删除: {kb_id}")
        return True

    # ======================== 文档关联 ========================

    def add_document(self, kb_id: str, doc_id: str) -> bool:
        """向知识库添加文档"""
        try:
            self.db.execute(
                "INSERT IGNORE INTO kb_documents (kb_id, doc_id) VALUES (%s, %s)",
                (kb_id, doc_id)
            )
            logger.info(f"文档 {doc_id} 已加入知识库 {kb_id}")
            return True
        except Exception as e:
            logger.error(f"添加文档到知识库失败: {e}")
            return False

    def add_documents_batch(self, kb_id: str, doc_ids: List[str]) -> int:
        """批量添加文档到知识库"""
        count = 0
        for doc_id in doc_ids:
            if self.add_document(kb_id, doc_id):
                count += 1
        return count

    def get_documents(self, kb_id: str, page: int = 1,
                      page_size: int = 20) -> Dict:
        """获取知识库中的文档列表"""
        offset = (page - 1) * page_size

        sql = """
            SELECT d.id, d.title, d.source, d.content, d.metadata,
                   d.created_at, kd.added_at as kb_added_at
            FROM kb_documents kd
            LEFT JOIN documents d ON kd.doc_id = d.id
            WHERE kd.kb_id = %s
            ORDER BY kd.added_at DESC
            LIMIT %s OFFSET %s
        """
        rows = self.db.query(sql, (kb_id, page_size, offset))

        count_row = self.db.query_one(
            "SELECT COUNT(*) as total FROM kb_documents WHERE kb_id = %s", (kb_id,)
        )
        total = count_row.get("total", 0) if count_row else 0

        docs = []
        for row in rows:
            meta = row.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except:
                    meta = {}

            docs.append({
                "id": row.get("id"),
                "doc_id": row.get("id"),
                "filename": row.get("title") or "未命名文档",
                "title": row.get("title"),
                "file_type": self._get_file_type(row.get("source") or ""),
                "source": row.get("source"),
                "chunk_count": 0,  # 下面从缓存注入实际值
                "content": row.get("content", ""),
                "added_at": str(row.get("kb_added_at", "")),
                "created_at": str(row.get("created_at", "")),
            })

        # 从 doc_chunk_counts.json 缓存注入每个文档的实际块数
        _inject_doc_chunk_counts(docs)

        return {"documents": docs, "total": total, "page": page, "page_size": page_size}

    # ======================== 搜索 ========================

    def search_knowledge_bases(self, keyword: str, top_k: int = 10) -> List[dict]:
        """全文搜索知识库"""
        sql = """SELECT * FROM knowledge_bases
                 WHERE name LIKE %s OR description LIKE %s
                 ORDER BY updated_at DESC LIMIT %s"""
        rows = self.db.query(sql, (f"%{keyword}%", f"%{keyword}%", top_k))
        return [self._row_to_kb(r).to_dict() for r in rows]

    def search_documents(self, keyword: str, kb_id: str = None,
                         top_k: int = 20) -> List[dict]:
        """搜索知识库内文档"""
        if kb_id:
            sql = """SELECT d.* FROM documents d
                     INNER JOIN kb_documents kd ON d.id = kd.doc_id
                     WHERE kd.kb_id = %s AND (d.title LIKE %s OR d.content LIKE %s)
                     LIMIT %s"""
            rows = self.db.query(sql, (kb_id, f"%{keyword}%", f"%{keyword}%", top_k))
        else:
            sql = """SELECT d.* FROM documents d
                     WHERE d.title LIKE %s OR d.content LIKE %s
                     LIMIT %s"""
            rows = self.db.query(sql, (f"%{keyword}%", f"%{keyword}%", top_k))

        return [
            {"doc_id": r.get("id"), "title": r.get("title"),
             "source": r.get("source"), "created_at": str(r.get("created_at", ""))}
            for r in rows
        ]

    # ======================== 统计 ========================

    def get_stats(self, kb_id: str) -> dict:
        """获取知识库统计信息（含 chunk 数和总大小）"""
        doc_count = self.db.query_one(
            "SELECT COUNT(*) as cnt FROM kb_documents WHERE kb_id = %s", (kb_id,)
        )
        doc_cnt = doc_count.get("cnt", 0) if doc_count else 0

        # 按 KB 统计 chunk 数和总大小（从 Milvus 查询）
        chunk_cnt = 0
        total_size = 0
        if doc_cnt > 0:
            try:
                from database.milvus_db import MilvusDB
                kb_docs = self.db.query(
                    "SELECT doc_id FROM kb_documents WHERE kb_id = %s", (kb_id,)
                )
                doc_ids = [r["doc_id"] for r in kb_docs]
                if doc_ids:
                    milvus = MilvusDB()
                    milvus.connect()
                    if milvus._client:
                        stats = milvus.get_doc_chunk_stats(doc_ids)
                        chunk_cnt = sum(s["chunk_count"] for s in stats.values())
                        total_size = sum(s["total_size"] for s in stats.values())
            except Exception as e:
                logger.warning(f"Milvus 统计 KB {kb_id} 失败: {e}")

        # 分类统计
        categories = self.db.query(
            "SELECT category, COUNT(*) as cnt FROM knowledge_bases GROUP BY category"
        )
        return {
            "kb_id": kb_id,
            "doc_count": doc_cnt,
            "chunk_count": chunk_cnt,
            "total_size": total_size,
            "category_distribution": [
                {"category": r.get("category"), "count": r.get("cnt")}
                for r in categories
            ],
        }

    # ======================== 内部方法 ========================

    @staticmethod
    def _get_file_type(source: str) -> str:
        """从 source 路径推断文件类型"""
        if not source:
            return "文档"
        ext_map = {
            "pdf": "PDF", "doc": "Word", "docx": "Word",
            "txt": "文本", "md": "Markdown", "py": "Python",
            "csv": "CSV", "xlsx": "Excel",
        }
        if "." in source:
            ext = source.rsplit(".", 1)[-1].lower()
            return ext_map.get(ext, ext.upper())
        return "文档"

    def _row_to_kb(self, row: dict) -> KnowledgeBase:
        tags = []
        if row.get("tags"):
            try:
                tags = json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
            except (json.JSONDecodeError, TypeError):
                pass

        return KnowledgeBase(
            kb_id=row.get("id"),
            name=row.get("name", ""),
            description=row.get("description", ""),
            category=row.get("category", "通用"),
            tags=tags,
            doc_count=row.get("doc_count", 0),
            created_at=str(row.get("created_at", "")),
            updated_at=str(row.get("updated_at", "")),
        )


def _inject_chunk_counts(items: list):
    """从轻量缓存文件注入 chunk_count（缺失时自动重建）"""
    try:
        from database.chunk_store import DOC_CHUNK_COUNT_FILE, CHUNK_FILE, rebuild_doc_chunk_counts
        if not os.path.exists(CHUNK_FILE):
            return
        if not os.path.exists(DOC_CHUNK_COUNT_FILE):
            rebuild_doc_chunk_counts()
        with open(DOC_CHUNK_COUNT_FILE, "r", encoding="utf-8") as f:
            doc_counts = json.load(f)
        if not doc_counts:
            return
        from database.mysql_db import MySQLDB
        db = MySQLDB()
        for item in items:
            kb_docs = db.query(
                "SELECT doc_id FROM kb_documents WHERE kb_id = %s", (item["id"],)
            )
            item["chunk_count"] = sum(
                doc_counts.get(r["doc_id"], 0) for r in kb_docs
            )
    except Exception as e:
        logger.debug(f"chunk_count 缓存读取失败: {e}")


def _inject_doc_chunk_counts(docs: list):
    """从 doc_chunk_counts.json 缓存注入每个文档的块数"""
    try:
        from database.chunk_store import DOC_CHUNK_COUNT_FILE, CHUNK_FILE, rebuild_doc_chunk_counts
        if not os.path.exists(CHUNK_FILE):
            return
        if not os.path.exists(DOC_CHUNK_COUNT_FILE):
            rebuild_doc_chunk_counts()
        with open(DOC_CHUNK_COUNT_FILE, "r", encoding="utf-8") as f:
            doc_counts = json.load(f)
        if not doc_counts:
            return
        for doc in docs:
            doc_id = doc.get("doc_id") or doc.get("id", "")
            doc["chunk_count"] = doc_counts.get(doc_id, 0)
    except Exception as e:
        logger.debug(f"doc_chunk_count 缓存读取失败: {e}")
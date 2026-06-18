"""
MySQL数据库操作
提供MySQL连接和常用数据库操作
"""
import pymysql
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from threading import Lock

try:
    from dbutils.pooled_db import PooledDB
    _has_dbutils = True
except ImportError:
    PooledDB = None
    _has_dbutils = False

from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("mysql_db")

_pool = None
_pool_lock = Lock()


def _get_connection(config: dict):
    """获取 MySQL 连接：优先使用连接池（DBUtils），回退到直连"""
    if _has_dbutils:
        global _pool
        if _pool is None:
            with _pool_lock:
                if _pool is None:
                    _pool = PooledDB(
                        creator=pymysql,
                        mincached=3,
                        maxcached=10,
                        maxconnections=50,
                        blocking=True,
                        host=config["host"],
                        port=config["port"],
                        user=config["user"],
                        password=config["password"],
                        database=config["database"],
                        charset=config.get("charset", "utf8mb4"),
                        cursorclass=pymysql.cursors.DictCursor,
                    )
                    logger.info(f"MySQL 连接池已创建 (max=50, host={config['host']})")
        return _pool.connection()
    else:
        return pymysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"],
            charset=config.get("charset", "utf8mb4"),
            cursorclass=pymysql.cursors.DictCursor,
        )


class MySQLDB:
    """MySQL数据库操作类"""

    def __init__(self):
        config = ConfigManager()
        self.config = config.mysql_config

    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器，自动关闭）"""
        conn = _get_connection(self.config)
        try:
            yield conn
        finally:
            conn.close()
    
    def execute(self, sql: str, params: tuple = None) -> int:
        """执行SQL语句（INSERT/UPDATE/DELETE）"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                affected_rows = cursor.execute(sql, params)
            conn.commit()
            return affected_rows
    
    def query(self, sql: str, params: tuple = None) -> List[Dict[str, Any]]:
        """执行查询SQL"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()
    
    def query_one(self, sql: str, params: tuple = None) -> Optional[Dict[str, Any]]:
        """查询单条记录"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()
    
    def init_tables(self):
        """初始化数据库表"""
        create_tables_sql = """
        CREATE TABLE IF NOT EXISTS documents (
            id VARCHAR(64) PRIMARY KEY,
            title VARCHAR(255),
            source VARCHAR(500),
            content LONGTEXT,
            md5_hash VARCHAR(32) DEFAULT NULL COMMENT '文档内容MD5哈希（用于去重）',
            metadata JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        
        CREATE TABLE IF NOT EXISTS faq (
            id VARCHAR(64) PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category VARCHAR(100),
            tags JSON,
            embedding JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        
        CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64),
            title VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id VARCHAR(64) PRIMARY KEY,
            conversation_id VARCHAR(64),
            role VARCHAR(20),
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        
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

        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(64) PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'student',
            display_name VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS feedback (
            id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL,
            conversation_id VARCHAR(64),
            query TEXT,
            answer TEXT,
            rating VARCHAR(10) NOT NULL COMMENT 'like 或 dislike',
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS evaluation_history (
            id VARCHAR(64) PRIMARY KEY,
            eval_type VARCHAR(32) NOT NULL COMMENT 'retrieval 或 ragas',
            config JSON COMMENT '评测配置参数',
            metrics JSON COMMENT '汇总指标',
            charts JSON COMMENT '图表 base64',
            sample_reports JSON COMMENT '各样本报告',
            details JSON COMMENT 'RAGAS 样本详情',
            sample_count INT DEFAULT 0 COMMENT '样本数',
            total_time FLOAT DEFAULT 0 COMMENT '总耗时(秒)',
            mode VARCHAR(32) DEFAULT '' COMMENT '评测模式(ragas/builtin)',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS wrong_book (
            id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL COMMENT '学生学号',
            subject VARCHAR(32) DEFAULT '通用' COMMENT '学科',
            question_type VARCHAR(20) DEFAULT 'subjective' COMMENT '题型: objective/subjective',
            question TEXT COMMENT '原题内容',
            user_answer TEXT COMMENT '用户作答',
            correct_answer TEXT COMMENT '正确答案',
            grading JSON COMMENT '批改结果(含得分/评语/高亮)',
            status VARCHAR(20) DEFAULT 'wrong' COMMENT '状态: wrong/corrected/reviewed',
            review_count INT DEFAULT 0 COMMENT '复习次数(艾宾浩斯遗忘曲线用)',
            last_reviewed_at TIMESTAMP NULL COMMENT '最后复习时间',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS query_logs (
            id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) DEFAULT '' COMMENT '用户ID',
            query TEXT NOT NULL COMMENT '查询内容',
            query_type VARCHAR(32) DEFAULT 'chat' COMMENT '查询类型: chat/grade',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_created_at (created_at),
            INDEX idx_user_id (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS user_profile (
            id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL COMMENT '用户ID',
            subject VARCHAR(32) NOT NULL DEFAULT '通用' COMMENT '学科',
            personality_tags JSON COMMENT '性格标签',
            ability_level VARCHAR(20) DEFAULT '未知' COMMENT '能力层级: 初级/中级/高级',
            weak_points JSON COMMENT '薄弱知识点 [{tag, frequency, last_error, mastery}]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_user_subject (user_id, subject),
            FOREIGN KEY (user_id) REFERENCES users(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        try:
            with self.get_connection() as conn:
                for sql in create_tables_sql.split(';'):
                    sql = sql.strip()
                    if sql:
                        with conn.cursor() as cursor:
                            cursor.execute(sql)
                conn.commit()
                # ===== 迁移：documents 表 md5_hash =====
                self._migrate_documents_md5(conn)
                # ===== 迁移：为已有 wrong_book 表添加复习字段 =====
                self._migrate_wrong_book(conn)
                # ===== 迁移：conversations 表 is_pinned =====
                self._migrate_conversations_pin(conn)
            logger.info("数据库表初始化完成")
        except Exception as e:
            logger.error(f"数据库表初始化失败: {e}")
            raise

    def _migrate_documents_md5(self, conn):
        """迁移：为已有 documents 表添加 md5_hash 列"""
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents'
                    AND COLUMN_NAME = 'md5_hash'
                """)
                if not cursor.fetchone():
                    cursor.execute(
                        "ALTER TABLE documents ADD COLUMN md5_hash VARCHAR(32) DEFAULT NULL COMMENT '文档内容MD5哈希（用于去重）'"
                    )
                    logger.info("迁移: documents 添加 md5_hash 列")
                    # 为已有文档计算 MD5
                    cursor.execute("SELECT id, content FROM documents WHERE md5_hash IS NULL AND content IS NOT NULL")
                    rows = cursor.fetchall()
                    if rows:
                        import hashlib
                        for row in rows:
                            md5 = hashlib.md5(row['content'].encode('utf-8', errors='replace')).hexdigest()
                            cursor.execute("UPDATE documents SET md5_hash = %s WHERE id = %s", (md5, row['id']))
                        logger.info(f"迁移: 为 {len(rows)} 篇已有文档计算 MD5")
                    conn.commit()
        except Exception as e:
            logger.warning(f"documents md5_hash 迁移失败（可忽略）: {e}")
    
    def _migrate_wrong_book(self, conn):
        """迁移：为已有错题表添加艾宾浩斯复习字段"""
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wrong_book'
                    AND COLUMN_NAME IN ('review_count', 'last_reviewed_at')
                """)
                existing = {r['COLUMN_NAME'] for r in cursor.fetchall()}
                if 'review_count' not in existing:
                    cursor.execute("ALTER TABLE wrong_book ADD COLUMN review_count INT DEFAULT 0 COMMENT '复习次数'")
                    logger.info("迁移: wrong_book 添加 review_count 列")
                if 'last_reviewed_at' not in existing:
                    cursor.execute("ALTER TABLE wrong_book ADD COLUMN last_reviewed_at TIMESTAMP NULL COMMENT '最后复习时间'")
                    logger.info("迁移: wrong_book 添加 last_reviewed_at 列")
                conn.commit()
        except Exception as e:
            logger.warning(f"错题表迁移失败（可忽略）: {e}")
    
    def _migrate_conversations_pin(self, conn):
        """迁移：为已有 conversations 表添加 is_pinned 列"""
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversations'
                    AND COLUMN_NAME = 'is_pinned'
                """)
                if not cursor.fetchone():
                    cursor.execute(
                        "ALTER TABLE conversations ADD COLUMN is_pinned TINYINT(1) DEFAULT 0 COMMENT '是否置顶'"
                    )
                    logger.info("迁移: conversations 添加 is_pinned 列")
                    conn.commit()
        except Exception as e:
            logger.warning(f"conversations表迁移失败（可忽略）: {e}")
    
    def log_query(self, user_id: str, query: str, query_type: str = "chat"):
        """记录查询日志（不阻断主流程）"""
        try:
            import uuid
            query_id = str(uuid.uuid4())
            self.execute(
                "INSERT INTO query_logs (id, user_id, query, query_type) VALUES (%s, %s, %s, %s)",
                (query_id, user_id or '', query[:2000], query_type)
            )
        except Exception as e:
            logger.warning(f"记录查询日志失败: {e}")

    def insert_document(self, doc_id: str, title: str, source: str, 
                       content: str, metadata: Dict = None, md5_hash: str = None) -> int:
        """插入文档记录（含 MD5 哈希用于去重）"""
        import hashlib
        if md5_hash is None and content:
            md5_hash = hashlib.md5(content.encode('utf-8', errors='replace')).hexdigest()
        sql = """
        INSERT INTO documents (id, title, source, content, md5_hash, metadata)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        import json
        return self.execute(sql, (doc_id, title, source, content, md5_hash, json.dumps(metadata or {})))
    
    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """获取文档"""
        sql = "SELECT id, title, source, content, md5_hash, metadata, created_at, updated_at FROM documents WHERE id = %s"
        return self.query_one(sql, (doc_id,))
    
    def get_document_by_md5(self, md5_hash: str) -> Optional[Dict[str, Any]]:
        """根据 MD5 哈希查找文档（用于去重）"""
        sql = "SELECT id, title, source, created_at FROM documents WHERE md5_hash = %s LIMIT 1"
        return self.query_one(sql, (md5_hash,))

    def get_document_by_md5_in_kb(self, md5_hash: str, kb_id: str) -> Optional[Dict[str, Any]]:
        """根据 MD5 哈希查找文档（限定在指定知识库范围内）"""
        sql = """SELECT d.id, d.title, d.source, d.created_at
                 FROM documents d
                 INNER JOIN kb_documents kd ON d.id = kd.doc_id
                 WHERE d.md5_hash = %s AND kd.kb_id = %s LIMIT 1"""
        return self.query_one(sql, (md5_hash, kb_id))

    def get_document_by_md5_global(self, md5_hash: str) -> Optional[Dict[str, Any]]:
        """根据 MD5 哈希查找文档（全局，带 KB 关联信息）"""
        sql = """SELECT d.id, d.title, d.source, d.created_at
                 FROM documents d
                 WHERE d.md5_hash = %s LIMIT 1"""
        return self.query_one(sql, (md5_hash,))

    def cleanup_orphan_documents(self) -> int:
        """清理不被任何知识库引用的孤立文档，返回删除数量"""
        result = self.query("SELECT COUNT(*) as cnt FROM documents d WHERE NOT EXISTS (SELECT 1 FROM kb_documents kd WHERE kd.doc_id = d.id)")
        cnt = result[0]['cnt'] if result else 0
        if cnt > 0:
            self.execute("DELETE FROM documents WHERE NOT EXISTS (SELECT 1 FROM kb_documents kd WHERE kd.doc_id = documents.id)")
            logger.info(f"清理了 {cnt} 个孤立文档记录")
        return cnt

    def get_all_documents_content(self) -> List[Dict[str, Any]]:
        """获取所有文档的 id, content, md5_hash（用于构建去重索引）"""
        sql = "SELECT id, content, md5_hash, title FROM documents WHERE content IS NOT NULL"
        return self.query(sql)

    def delete_document(self, doc_id: str) -> int:
        """删除文档"""
        sql = "DELETE FROM documents WHERE id = %s"
        return self.execute(sql, (doc_id,))

    # ==================== 用户操作 ====================

    def create_user(self, user_id: str, username: str, password_hash: str,
                    role: str = "student", display_name: str = "") -> int:
        """创建用户"""
        sql = """INSERT INTO users (id, username, password_hash, role, display_name)
                 VALUES (%s, %s, %s, %s, %s)"""
        return self.execute(sql, (user_id, username, password_hash, role, display_name))

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """根据用户名查用户"""
        sql = "SELECT id, username, password_hash, role, display_name, created_at FROM users WHERE username = %s"
        return self.query_one(sql, (username,))

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """根据ID查用户"""
        sql = "SELECT id, username, password_hash, role, display_name, created_at FROM users WHERE id = %s"
        return self.query_one(sql, (user_id,))

    def list_users(self, role: str = None) -> List[Dict[str, Any]]:
        """列出用户"""
        if role:
            sql = "SELECT id, username, role, display_name, created_at FROM users WHERE role = %s"
            return self.query(sql, (role,))
        sql = "SELECT id, username, role, display_name, created_at FROM users"
        return self.query(sql)

    # ==================== 反馈操作 ====================

    def insert_feedback(self, feedback_id: str, user_id: str, conversation_id: str,
                        query: str, answer: str, rating: str, comment: str = "") -> int:
        """插入反馈"""
        sql = """INSERT INTO feedback (id, user_id, conversation_id, query, answer, rating, comment)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)"""
        return self.execute(sql, (feedback_id, user_id, conversation_id, query, answer, rating, comment))

    def get_feedback_stats(self) -> Dict[str, Any]:
        """获取反馈统计"""
        total = self.query_one("SELECT COUNT(*) as cnt FROM feedback")
        likes = self.query_one("SELECT COUNT(*) as cnt FROM feedback WHERE rating = 'like'")
        dislikes = self.query_one("SELECT COUNT(*) as cnt FROM feedback WHERE rating = 'dislike'")
        return {
            "total": total["cnt"] if total else 0,
            "likes": likes["cnt"] if likes else 0,
            "dislikes": dislikes["cnt"] if dislikes else 0,
            "like_rate": round(likes["cnt"] / max(total["cnt"], 1), 2) if total else 0.0
        }

    # ==================== 知识库操作 ====================

    def create_knowledge_base(self, kb_id: str, name: str, description: str = "",
                              category: str = "通用", tags: List[str] = None) -> int:
        """创建知识库"""
        import json
        sql = """INSERT INTO knowledge_bases (id, name, description, category, tags)
                 VALUES (%s, %s, %s, %s, %s)"""
        return self.execute(sql, (kb_id, name, description, category, json.dumps(tags or [])))

    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        """列出所有知识库"""
        sql = "SELECT id, name, description, category, tags, created_at, updated_at FROM knowledge_bases ORDER BY created_at DESC"
        return self.query(sql)

    def get_knowledge_base(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """获取单个知识库"""
        sql = "SELECT id, name, description, category, tags, created_at, updated_at FROM knowledge_bases WHERE id = %s"
        return self.query_one(sql, (kb_id,))

    def update_knowledge_base(self, kb_id: str, name: str = None, description: str = None,
                              category: str = None, tags: List[str] = None) -> int:
        """更新知识库"""
        import json
        fields = []
        params = []
        if name is not None:
            fields.append("name = %s")
            params.append(name)
        if description is not None:
            fields.append("description = %s")
            params.append(description)
        if category is not None:
            fields.append("category = %s")
            params.append(category)
        if tags is not None:
            fields.append("tags = %s")
            params.append(json.dumps(tags))
        if not fields:
            return 0
        params.append(kb_id)
        sql = f"UPDATE knowledge_bases SET {', '.join(fields)} WHERE id = %s"
        return self.execute(sql, tuple(params))

    def delete_knowledge_base(self, kb_id: str) -> int:
        """删除知识库（级联删除关联文档和孤立文档）"""
        # 1. 获取该KB关联的所有文档ID（在删除关联前获取）
        rows = self.query("SELECT doc_id FROM kb_documents WHERE kb_id = %s", (kb_id,))
        doc_id_list = [r['doc_id'] for r in rows] if rows else []

        # 2. 删除KB与文档的关联
        self.execute("DELETE FROM kb_documents WHERE kb_id = %s", (kb_id,))

        # 3. 删除知识库本身
        result = self.execute("DELETE FROM knowledge_bases WHERE id = %s", (kb_id,))

        # 4. 清理孤立文档：删除不再被任何KB引用的文档
        if doc_id_list:
            placeholders = ','.join(['%s'] * len(doc_id_list))
            still_referenced = self.query(
                f"SELECT DISTINCT doc_id FROM kb_documents WHERE doc_id IN ({placeholders})",
                tuple(doc_id_list)
            )
            referenced_ids = {r['doc_id'] for r in still_referenced} if still_referenced else set()
            orphan_ids = [did for did in doc_id_list if did not in referenced_ids]

            if orphan_ids:
                placeholders2 = ','.join(['%s'] * len(orphan_ids))
                self.execute(f"DELETE FROM documents WHERE id IN ({placeholders2})", tuple(orphan_ids))
                logger.info(f"删除知识库时清理了 {len(orphan_ids)} 个孤立文档")

        return result

    def add_doc_to_kb(self, kb_id: str, doc_id: str) -> int:
        """将文档加入知识库"""
        sql = "INSERT IGNORE INTO kb_documents (kb_id, doc_id) VALUES (%s, %s)"
        return self.execute(sql, (kb_id, doc_id))

    def get_kb_documents(self, kb_id: str) -> List[Dict[str, Any]]:
        """获取知识库中的所有文档"""
        sql = """SELECT d.* FROM documents d
                 INNER JOIN kb_documents kd ON d.id = kd.doc_id
                 WHERE kd.kb_id = %s"""
        return self.query(sql, (kb_id,))

    # ==================== 评测历史操作 ====================

    def insert_eval_history(self, history_id: str, eval_type: str, config: Dict = None,
                             metrics: Dict = None, charts: Dict = None,
                             sample_reports: List = None, details: List = None,
                             sample_count: int = 0, total_time: float = 0.0,
                             mode: str = "") -> int:
        """插入评测历史记录"""
        import json
        sql = """INSERT INTO evaluation_history
                 (id, eval_type, config, metrics, charts, sample_reports, details,
                  sample_count, total_time, mode)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        return self.execute(sql, (
            history_id, eval_type,
            json.dumps(config or {}, ensure_ascii=False),
            json.dumps(metrics or {}, ensure_ascii=False),
            json.dumps(charts or {}, ensure_ascii=False),
            json.dumps(sample_reports or [], ensure_ascii=False),
            json.dumps(details or [], ensure_ascii=False),
            sample_count, total_time, mode
        ))

    def list_eval_history(self, eval_type: str = None, limit: int = 20) -> List[Dict[str, Any]]:
        """列出评测历史（按时间倒序，不含图表大字段）"""
        if eval_type:
            sql = """SELECT id, eval_type, config, metrics, sample_count, total_time, mode, created_at
                     FROM evaluation_history WHERE eval_type = %s
                     ORDER BY created_at DESC LIMIT %s"""
            return self.query(sql, (eval_type, limit))
        sql = """SELECT id, eval_type, config, metrics, sample_count, total_time, mode, created_at
                 FROM evaluation_history ORDER BY created_at DESC LIMIT %s"""
        return self.query(sql, (limit,))

    def get_eval_history(self, history_id: str) -> Optional[Dict[str, Any]]:
        """获取单条评测历史详情（含完整数据）"""
        sql = "SELECT id, eval_type, config, metrics, charts, sample_reports, details, sample_count, total_time, mode, created_at FROM evaluation_history WHERE id = %s"
        return self.query_one(sql, (history_id,))

    def delete_eval_history(self, history_id: str) -> int:
        """删除评测历史"""
        sql = "DELETE FROM evaluation_history WHERE id = %s"
        return self.execute(sql, (history_id,))

    # ==================== 错题集操作 ====================

    def insert_wrong_book(self, wb_id: str, user_id: str, subject: str = "通用",
                           question_type: str = "subjective", question: str = "",
                           user_answer: str = "", correct_answer: str = "",
                           grading: Dict = None, status: str = "wrong") -> int:
        """新增错题"""
        import json
        sql = """INSERT INTO wrong_book
                 (id, user_id, subject, question_type, question, user_answer,
                  correct_answer, grading, status, review_count, last_reviewed_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)"""
        return self.execute(sql, (
            wb_id, user_id, subject, question_type, question, user_answer,
            correct_answer, json.dumps(grading or {}, ensure_ascii=False), status, 0
        ))

    def list_wrong_book(self, user_id: str, subject: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """获取错题列表"""
        _cols = "id, user_id, subject, question_type, question, user_answer, correct_answer, grading, status, review_count, last_reviewed_at, created_at"
        if subject:
            sql = f"SELECT {_cols} FROM wrong_book WHERE user_id = %s AND subject = %s ORDER BY created_at DESC LIMIT %s"
            return self.query(sql, (user_id, subject, limit))
        sql = f"SELECT {_cols} FROM wrong_book WHERE user_id = %s ORDER BY created_at DESC LIMIT %s"
        return self.query(sql, (user_id, limit))

    def get_wrong_book_stats(self, user_id: str) -> Dict[str, Any]:
        """错题集统计"""
        sql = """SELECT subject, question_type, COUNT(*) as cnt
                 FROM wrong_book WHERE user_id = %s
                 GROUP BY subject, question_type"""
        rows = self.query(sql, (user_id,))
        total = sum(r['cnt'] for r in rows)
        return {"total": total, "by_subject": rows}

    def delete_wrong_book(self, wb_id: str, user_id: str = None) -> int:
        """删除错题"""
        if user_id:
            sql = "DELETE FROM wrong_book WHERE id = %s AND user_id = %s"
            return self.execute(sql, (wb_id, user_id))
        sql = "DELETE FROM wrong_book WHERE id = %s"
        return self.execute(sql, (wb_id,))

    def get_wrong_book_by_id(self, wb_id: str) -> Dict[str, Any]:
        """获取单条错题"""
        return self.query_one(
            "SELECT id, user_id, subject, question_type, question, user_answer, correct_answer, grading, status, review_count, last_reviewed_at, created_at FROM wrong_book WHERE id = %s",
            (wb_id,)
        )

    def review_wrong_book(self, wb_id: str) -> int:
        """记录复习（艾宾浩斯遗忘曲线）"""
        return self.execute(
            "UPDATE wrong_book SET review_count = review_count + 1, last_reviewed_at = NOW() WHERE id = %s",
            (wb_id,)
        )

    # ==================== 用户画像操作 ====================

    def upsert_user_profile(self, user_id: str, subject: str,
                            personality_tags: list = None,
                            ability_level: str = None,
                            weak_points: list = None) -> int:
        """插入或更新用户画像"""
        import json
        profile_id = str(__import__('uuid').uuid4())
        existing = self.query_one(
            "SELECT id FROM user_profile WHERE user_id = %s AND subject = %s",
            (user_id, subject)
        )
        if existing:
            fields, params = [], []
            if personality_tags is not None:
                fields.append("personality_tags = %s")
                params.append(json.dumps(personality_tags, ensure_ascii=False))
            if ability_level is not None:
                fields.append("ability_level = %s")
                params.append(ability_level)
            if weak_points is not None:
                fields.append("weak_points = %s")
                params.append(json.dumps(weak_points, ensure_ascii=False))
            if not fields:
                return 0
            params.append(existing["id"])
            return self.execute(
                f"UPDATE user_profile SET {', '.join(fields)} WHERE id = %s",
                tuple(params)
            )
        else:
            return self.execute(
                """INSERT INTO user_profile (id, user_id, subject, personality_tags, ability_level, weak_points)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (profile_id, user_id, subject,
                 json.dumps(personality_tags or [], ensure_ascii=False),
                 ability_level or "未知",
                 json.dumps(weak_points or [], ensure_ascii=False))
            )

    def get_user_profile(self, user_id: str, subject: str = None) -> dict:
        """获取用户画像，指定学科则返回单条，否则返回全部学科"""
        import json
        _cols = "id, user_id, subject, personality_tags, ability_level, weak_points, updated_at"
        if subject:
            row = self.query_one(
                f"SELECT {_cols} FROM user_profile WHERE user_id = %s AND subject = %s",
                (user_id, subject)
            )
            if row:
                row["personality_tags"] = json.loads(row.get("personality_tags") or "[]")
                row["weak_points"] = json.loads(row.get("weak_points") or "[]")
            return row
        rows = self.query(
            f"SELECT {_cols} FROM user_profile WHERE user_id = %s", (user_id,)
        )
        for row in rows:
            row["personality_tags"] = json.loads(row.get("personality_tags") or "[]")
            row["weak_points"] = json.loads(row.get("weak_points") or "[]")
        return rows

"""对话历史持久化辅助函数"""
import uuid
from typing import List


def save_conversation_message(conversation_id: str, role: str, content: str):
    """保存对话消息到MySQL，同时更新会话标题和更新时间"""
    import logging
    _log = logging.getLogger("conv_helpers")
    try:
        from database.mysql_db import MySQLDB
        db = MySQLDB()
        db.execute(
            "INSERT IGNORE INTO conversations (id, title) VALUES (%s, %s)",
            (conversation_id, "新对话")
        )
        msg_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO conversation_messages (id, conversation_id, role, content) VALUES (%s, %s, %s, %s)",
            (msg_id, conversation_id, role, content[:2000])
        )
        if role == "user":
            title = content[:30].replace('\n', ' ').strip() or "新对话"
            db.execute(
                "UPDATE conversations SET title = %s, updated_at = NOW() WHERE id = %s AND title = '新对话'",
                (title, conversation_id)
            )
        elif role == "assistant":
            db.execute("UPDATE conversations SET updated_at = NOW() WHERE id = %s", (conversation_id,))
    except Exception as e:
        _log.warning(f"保存对话消息失败 (conv={conversation_id}): {e}")


def load_conversation_history(conversation_id: str) -> List[dict]:
    """从MySQL加载对话历史"""
    try:
        from database.mysql_db import MySQLDB
        db = MySQLDB()
        rows = db.query(
            "SELECT role, content FROM conversation_messages "
            "WHERE conversation_id = %s ORDER BY created_at ASC LIMIT 20",
            (conversation_id,)
        )
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    except Exception:
        return []

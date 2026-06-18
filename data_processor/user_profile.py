"""
用户画像自动提取

三个维度的提取逻辑:
- ability_level: 规则计算（批改正确率），无需 LLM
- weak_points: LLM 归类 wrong_book.grading 中的 error_type → 标准化知识点标签
- personality_tags: LLM 分析对话历史中的提问风格

提取触发时机:
- 批改保存后 → 更新 ability_level + weak_points
- 累计 20 轮对话后 → 更新 personality_tags（异步，首次分析后每 20 轮增量更新）
"""
import json
from typing import List, Dict, Optional
from datetime import datetime

from core.logger import get_logger
from database.mysql_db import MySQLDB

logger = get_logger("user_profile")

ABILITY_THRESHOLDS = {
    "高级": 0.85,
    "中级": 0.50,
    "初级": 0.0,
}

WEAK_POINT_EXTRACT_PROMPT = """你是一个教育知识点分析专家。请根据以下学生的错题记录，将错误归类为标准化知识点标签。

要求：
1. 标签格式："学科-知识模块-具体知识点"，如"数学-分数-通分"、"英语-时态-现在完成时"
2. 同一知识点的多次错误合并为一条，统计频率
3. 只输出 JSON 数组，不要解释

【学科】{subject}
【错题记录】
{error_records}

返回格式：
[{{"tag": "数学-分数-通分", "frequency": 3}}, {{"tag": "数学-方程-移项", "frequency": 1}}]"""

PERSONALITY_EXTRACT_PROMPT = """你是一个学习行为分析专家。请根据以下学生的对话记录，分析其学习性格和提问风格。

性格标签从以下维度判断（每个维度最多 1 个标签）：
- 追问深度：钻研型（追问≥3轮）/ 点到为止型
- 表达偏好：具象型（要求举例/画图）/ 抽象型（接受概念解释）
- 话题广度：聚焦型（单一学科）/ 探索型（跨学科频繁切换）
- 响应风格：效率型（问题简短直接）/ 思辨型（喜欢追问为什么）

【对话记录】
{conversation_history}

返回 JSON 数组（最多 4 个标签）：
["钻研型", "具象型", ...]

只返回 JSON 数组，不要解释。"""


def update_ability_level(user_id: str, subject: str) -> Optional[str]:
    """从 wrong_book 统计正确率，规则判定能力层级"""
    db = MySQLDB()
    rows = db.list_wrong_book(user_id, subject, limit=200)
    if not rows:
        return None

    total = len(rows)
    corrected = sum(1 for r in rows if r.get("status") == "corrected")
    # 每次批改都有 score，从 grading JSON 提取
    scores = []
    for r in rows:
        grading = r.get("grading")
        if isinstance(grading, str):
            try:
                grading = json.loads(grading)
            except json.JSONDecodeError:
                grading = {}
        if isinstance(grading, dict) and "score" in grading:
            scores.append(float(grading["score"]))

    if not scores:
        # 只看错题状态占比
        wrong_rate = (total - corrected) / total
        accuracy = 1.0 - wrong_rate
    else:
        accuracy = sum(scores) / (len(scores) * 100)

    for level, threshold in ABILITY_THRESHOLDS.items():
        if accuracy >= threshold:
            return level
    return "初级"


def update_weak_points(user_id: str, subject: str) -> Optional[List[dict]]:
    """从 wrong_book 的 grading JSON 中提取错误维度，LLM 归类为知识点标签"""
    db = MySQLDB()
    rows = db.list_wrong_book(user_id, subject, limit=30)
    if not rows:
        return None

    # 提取结构化错误信息
    records = []
    for i, r in enumerate(rows):
        grading = r.get("grading")
        if isinstance(grading, str):
            try:
                grading = json.loads(grading)
            except json.JSONDecodeError:
                grading = {}
        if not isinstance(grading, dict):
            continue

        parts = []
        # 错误类型
        highlights = grading.get("highlights", [])
        error_types = [h.get("error_type", "") for h in highlights if h.get("error_type")]
        if error_types:
            parts.append(f"错误类型: {', '.join(error_types)}")
        # 薄弱维度
        weaknesses = grading.get("details", {}).get("weaknesses", [])
        if weaknesses:
            parts.append(f"薄弱点: {'; '.join(weaknesses[:3])}")
        # 关键点评分
        key_points = grading.get("details", {}).get("key_points", [])
        weak_kps = [kp for kp in key_points if kp.get("quality") in ("partial", "missing")]
        if weak_kps:
            parts.append(f"未掌握: {'; '.join(kp.get('point', '') for kp in weak_kps[:3])}")
        # 建议
        suggestions = grading.get("suggestions", [])
        if suggestions:
            parts.append(f"建议: {'; '.join(suggestions[:2])}")

        if parts:
            records.append(f"[{i+1}] {' | '.join(parts)}")

    if not records:
        return None

    error_text = "\n".join(records[:15])
    prompt = WEAK_POINT_EXTRACT_PROMPT.format(subject=subject, error_records=error_text)

    try:
        from llm.llm_client import get_fast_llm
        llm = get_fast_llm()
        resp = llm.generate(prompt, max_tokens=300, temperature=0.1)
        tags = _parse_json_array(resp)
        logger.info(f"weak_points 提取: user={user_id}, subject={subject}, tags={tags}")
        return tags
    except Exception as e:
        logger.warning(f"weak_points 提取失败: {e}")
        return None


def update_personality(user_id: str) -> Optional[List[str]]:
    """从对话历史分析学习性格，累计 20 轮后触发"""
    db = MySQLDB()
    # 获取最近对话消息（取最近 3 个 conversation 的消息）
    convs = db.query(
        "SELECT id FROM conversations WHERE user_id = %s ORDER BY updated_at DESC LIMIT 3",
        (user_id,)
    )
    if not convs:
        return None

    conv_ids = [c["id"] for c in convs]
    placeholders = ",".join(["%s"] * len(conv_ids))
    rows = db.query(
        f"SELECT role, content FROM conversation_messages WHERE conversation_id IN ({placeholders}) ORDER BY created_at ASC LIMIT 100",
        tuple(conv_ids)
    )
    if len(rows) < 10:  # 至少 10 条消息才开始分析
        return None

    history_text = "\n".join(
        f"[{'学生' if r['role'] == 'user' else '助手'}]: {r['content'][:200]}"
        for r in rows[-60:]
    )

    prompt = PERSONALITY_EXTRACT_PROMPT.format(conversation_history=history_text)

    try:
        from llm.llm_client import get_fast_llm
        llm = get_fast_llm()
        resp = llm.generate(prompt, max_tokens=150, temperature=0.1)
        tags = _parse_json_array(resp)
        logger.info(f"personality 提取: user={user_id}, tags={tags}")
        return tags
    except Exception as e:
        logger.warning(f"personality 提取失败: {e}")
        return None


def refresh_user_profile(user_id: str, subject: str = "通用",
                         trigger_personality: bool = False) -> Optional[dict]:
    """
    刷新用户画像 — 批改后调用

    Args:
        user_id: 用户ID
        subject: 学科
        trigger_personality: 是否同时分析性格（批改时一般不触发，对话触发）

    Returns:
        更新后的 profile dict，无数据时返回 None
    """
    db = MySQLDB()

    # 1. 能力层级（规则，实时）
    ability = update_ability_level(user_id, subject)

    # 2. 易错点（LLM 归类，实时）
    weak_points = update_weak_points(user_id, subject)

    # 3. 性格（LLM 分析对话，仅满足触发条件时执行）
    personality = None
    if trigger_personality:
        personality = update_personality(user_id)

    # 合并已有 personality（非触发时不覆盖）
    if personality is None and not trigger_personality:
        existing = db.get_user_profile(user_id, subject)
        if existing and existing.get("personality_tags"):
            personality = existing["personality_tags"]

    # 写库
    db.upsert_user_profile(
        user_id=user_id,
        subject=subject,
        personality_tags=personality,
        ability_level=ability,
        weak_points=weak_points,
    )

    return db.get_user_profile(user_id, subject)


def build_profile_section(profile: dict) -> str:
    """将用户画像构建为注入提示词的文本段落"""
    if not profile:
        return ""

    parts = []

    personality = profile.get("personality_tags")
    if isinstance(personality, str):
        personality = json.loads(personality)
    if personality:
        parts.append(f"性格：{'、'.join(personality)}")

    ability = profile.get("ability_level", "")
    if ability and ability != "未知":
        parts.append(f"能力层级：{ability}")

    weak_points = profile.get("weak_points")
    if isinstance(weak_points, str):
        weak_points = json.loads(weak_points)
    if weak_points:
        tags = ", ".join(
            f'{p["tag"]}(错{p.get("frequency", 1)}次)'
            for p in weak_points[:5]
        )
        parts.append(f"薄弱知识点：{tags}")

    if not parts:
        return ""

    return "【学生画像】\n" + "\n".join(f"- {p}" for p in parts) + "\n\n"


def _parse_json_array(text: str) -> list:
    """从 LLM 返回中解析 JSON 数组"""
    import re
    if not text:
        return []
    text = text.strip()
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # try full text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    return []

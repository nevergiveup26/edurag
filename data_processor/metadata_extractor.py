"""
元数据提取器

从文档内容和用户查询中提取学科（subject）、年级（grade）、文档类型（doc_type）等元数据标签。
用于元数据过滤检索，帮助在相关学科/年级范围内精准检索。

用法：
    # 从文档提取元数据
    extractor = MetadataExtractor()
    metadata = extractor.extract_from_document(
        text="一元一次方程的解法：设未知数为x...",
        filename="初一数学教案.docx"
    )
    # → {"subject": "数学", "grade": "初中", "doc_type": "教案"}

    # 从查询提取过滤条件
    filters = extractor.extract_from_query("初一数学的一元一次方程怎么解")
    # → {"subject": "数学", "grade": "初中"}
"""
import os
import re
from typing import Dict, Optional
from core.logger import get_logger

logger = get_logger("metadata_extractor")

# ========== 学科关键词映射 ==========
SUBJECT_KEYWORDS = {
    "数学": ["数学", "代数", "几何", "方程", "函数", "概率", "统计", "三角", "数列", "微积分",
             "一元一次", "二元一次", "一元二次", "勾股定理", "圆周率", "加减乘除", "乘法", "除法",
             "加法", "减法", "分数", "小数", "整数", "正数", "负数", "平方", "立方", "开方"],
    "语文": ["语文", "课文", "古诗", "唐诗", "宋词", "元曲", "文言文", "现代文", "阅读", "作文",
             "写作", "修辞", "比喻", "拟人", "排比", "夸张", "对联", "拼音", "汉字", "笔画",
             "春晓", "静夜思", "背影", "荷塘月色", "论语"],
    "英语": ["英语", "英文", "单词", "语法", "时态", "过去式", "现在进行时", "将来时",
             "名词", "动词", "形容词", "副词", "介词", "连词", "阅读", "听力", "口语",
             "grammar", "vocabulary", "tense", "sentence", "TOEFL", "雅思", "四级"],
    "物理": ["物理", "力学", "电学", "光学", "热学", "声学", "磁场", "电场", "牛顿",
             "爱因斯坦", "相对论", "量子", "速度", "加速度", "重力", "浮力", "压强", "电路"],
    "化学": ["化学", "元素", "反应", "分子", "原子", "化学式", "方程式", "酸碱", "氧化",
             "还原", "催化剂", "电解", "化学键", "有机", "无机", "周期表"],
    "生物": ["生物", "细胞", "基因", "DNA", "RNA", "蛋白质", "光合作用", "呼吸作用",
             "生态系统", "遗传", "进化", "物种", "微生物", "动物", "植物", "人体"],
    "历史": ["历史", "朝代", "皇帝", "战争", "革命", "改革", "古代", "近代", "现代",
             "秦汉", "唐宋", "元明", "清朝", "民国", "新中国", "世界史"],
    "地理": ["地理", "地图", "气候", "地形", "山脉", "河流", "海洋", "大陆", "国家",
             "省份", "城市", "经纬度", "时区", "自然", "人文", "环境"],
    "政治": ["政治", "法律", "宪法", "公民", "权利", "义务", "民主", "法制", "道德",
             "社会主义核心价值观", "人民代表大会"],
    "信息技术": ["计算机", "编程", "Python", "算法", "数据结构", "网络", "数据库",
               "人工智能", "代码", "程序", "软件", "硬件"],
    "教育综合": ["教育", "教学", "课程", "课标", "新课改", "素质教育", "核心素养",
               "双减", "考试", "高考", "中考", "期末", "教案", "课件"],
}

# ========== 年级关键词映射 ==========
GRADE_KEYWORDS = {
    "小学": ["小学", "一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
             "小学生", "加减法", "乘法口诀", "拼音"],
    "初中": ["初中", "初一", "初二", "初三", "七年级", "八年级", "九年级",
             "中考", "中学生", "青春期"],
    "高中": ["高中", "高一", "高二", "高三", "高考", "高中生",
             "必修", "选修", "学业水平"],
    "大学": ["大学", "本科", "研究生", "硕士", "博士", "高等教育",
             "专业课", "公共课"],
}

# ========== 文档类型关键词映射 ==========
DOC_TYPE_KEYWORDS = {
    "教案": ["教案", "教学设计", "教学目标", "教学重点", "教学难点", "教学过程",
             "课堂导入", "板书设计", "教学反思", "课时安排"],
    "课件": ["课件", "PPT", "幻灯片", "演示文稿", "多媒体课件"],
    "试题": ["试题", "试卷", "考试", "测试", "练习题", "习题", "真题", "模拟",
             "选择题", "填空题", "判断题", "问答题", "解答题", "计算题"],
    "教材": ["教材", "课本", "教科书", "必修", "选修", "章节", "单元"],
    "论文": ["论文", "研究", "摘要", "关键词", "参考文献", "结论", "致谢"],
    "标准": ["课程标准", "课标", "教学大纲", "考试大纲", "考纲"],
    "总结": ["总结", "报告", "分析报告", "年度总结", "学期总结"],
}


class MetadataExtractor:
    """元数据提取器 — 从文本和文件名推断 学科/年级/文档类型"""

    def extract_from_document(self, text: str, filename: str = "",
                              max_text_chars: int = 3000) -> Dict[str, str]:
        """
        从文档内容和文件名提取元数据

        Args:
            text: 文档文本内容
            filename: 文件名
            max_text_chars: 分析的最大字符数（避免处理大文件太慢）

        Returns:
            {"subject": "数学", "grade": "初中", "doc_type": "教案"} 或空dict
        """
        analysis_text = text[:max_text_chars].lower()
        combined = analysis_text + " " + filename.lower()

        result = {}

        # 提取学科
        subject = self._match_category(combined, SUBJECT_KEYWORDS)
        if subject:
            result["subject"] = subject

        # 提取年级
        grade = self._match_category(combined, GRADE_KEYWORDS)
        if grade:
            result["grade"] = grade

        # 提取文档类型
        doc_type = self._match_category(combined, DOC_TYPE_KEYWORDS)
        if doc_type:
            result["doc_type"] = doc_type

        if result:
            logger.debug(f"文档元数据提取: {filename[:30]} → {result}")
        return result

    def extract_from_query(self, query: str) -> Dict[str, str]:
        """
        从用户查询中提取元数据过滤条件

        Args:
            query: 用户查询文本

        Returns:
            {"subject": "数学", "grade": "初中"} — 可用于检索过滤
        """
        query_lower = query.lower()
        result = {}

        # 提取学科
        subject = self._match_category(query_lower, SUBJECT_KEYWORDS)
        if subject:
            result["subject"] = subject

        # 提取年级
        grade = self._match_category(query_lower, GRADE_KEYWORDS)
        if grade:
            result["grade"] = grade

        # 提取文档类型偏好
        doc_type = self._match_category(query_lower, DOC_TYPE_KEYWORDS)
        if doc_type:
            result["doc_type"] = doc_type

        return result

    def _match_category(self, text: str, category_map: Dict[str, list]) -> Optional[str]:
        """
        基于关键词匹配，返回得分最高的类别
        超过阈值才返回，避免误匹配
        """
        best_category = None
        best_score = 0

        for category, keywords in category_map.items():
            score = 0
            for kw in keywords:
                if kw.lower() in text:
                    # 长关键词权重更高
                    score += len(kw)
            if score > best_score:
                best_score = score
                best_category = category

        # 需要至少2个字符的累积匹配才认定
        if best_score >= 2 and best_category:
            return best_category
        return None

    def build_milvus_filter_expr(self, metadata_filter: Dict[str, str]) -> str:
        """
        将元数据过滤条件构建为 Milvus 过滤表达式

        Milvus JSON 字段支持: metadata["subject"] == "数学"

        Args:
            metadata_filter: {"subject": "数学", "grade": "初中"}

        Returns:
            过滤表达式字符串
        """
        parts = []
        for key, value in metadata_filter.items():
            # Milvus expr: metadata["field"] == "value"
            parts.append(f'metadata["{key}"] == "{value}"')
        if parts:
            return " and ".join(parts)
        return ""

    @staticmethod
    def matches_filter(chunk_metadata: Dict, metadata_filter: Dict[str, str]) -> bool:
        """
        检查 chunk 元数据是否匹配过滤条件（用于内存检索的后过滤）

        Args:
            chunk_metadata: chunk 的 metadata 字段
            metadata_filter: 过滤条件 {"subject": "数学", "grade": "初中"}

        Returns:
            是否匹配
        """
        if not metadata_filter or not chunk_metadata:
            return True

        for key, expected_value in metadata_filter.items():
            actual_value = chunk_metadata.get(key, "")
            if actual_value and actual_value != expected_value:
                return False
        return True
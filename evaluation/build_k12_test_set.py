"""
从 K-12 题库构建教育领域 RAG 评估测试集

从 original_data 中抽取各年级/学科的题目，转为 RAG 评估用的 QA 样本。
优先选取有详细 analysis 的题目，保证答案质量。
"""
import json
import os
import random
from pathlib import Path

random.seed(42)

BASE_DIR = Path(__file__).parent.parent / "data" / "external" / "k12_question_bank" / "original_data"
OUTPUT_PATH = Path(__file__).parent / "k12_test_set.json"

# 每个(年级, 学科)抽取的题目数上限
SAMPLE_CONFIG = {
    ("小学", "语文"): 10,
    ("小学", "数学"): 10,
    ("小学", "英语"): 10,
    ("初中", "语文"): 5,
    ("初中", "数学"): 5,
    ("初中", "物理"): 5,
    ("初中", "化学"): 5,
}


def _clean_latex(text: str) -> str:
    """移除 $$ 标记符号，保留纯文本"""
    return text.replace("$$", "").strip()


def _make_rag_query(prompt: str, answer_option: list) -> str:
    """将选择题 prompt + 选项合并为 RAG query"""
    prompt_clean = _clean_latex(prompt).strip()
    if not answer_option:
        return prompt_clean
    options_text = " ".join(_clean_latex(opt).strip() for opt in answer_option)
    return f"{prompt_clean}\n{options_text}"


def _make_expected_answer(item: dict) -> str:
    """用 analysis + answer 构造参考答案"""
    answer = _clean_latex(item.get("answer", ""))
    analysis = _clean_latex(item.get("analysis", ""))
    if analysis:
        return f"{answer}\n{analysis}"
    return answer


def _extract_keywords(item: dict) -> list:
    """从 knowledge_tree 提取关键词"""
    tree = item.get("knowledge_tree", "")
    parts = [p.strip() for p in tree.replace("「", "").replace("」", "").split("-") if p.strip()]
    # 去重并限制数量
    seen = set()
    keywords = []
    for p in parts:
        if p not in seen:
            keywords.append(p)
            seen.add(p)
    return keywords[:5]


def build():
    samples = []

    for (grade, subject), limit in SAMPLE_CONFIG.items():
        subject_dir = BASE_DIR / grade / subject
        if not subject_dir.exists():
            print(f"  SKIP: {subject_dir} 不存在")
            continue

        # 优先选取有 analysis 的题目
        all_items = []
        for fpath in subject_dir.glob("*.jsonl"):
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    all_items.append(item)

        # 优先选有详细 analysis 的（长度 > 30 字符）
        with_analysis = [it for it in all_items if len(it.get("analysis", "")) > 30]
        without_analysis = [it for it in all_items if len(it.get("analysis", "")) <= 30]

        selected = []
        # 80% 从有 analysis 的选
        n_analysis = min(int(limit * 0.8), len(with_analysis))
        if n_analysis > 0:
            selected.extend(random.sample(with_analysis, n_analysis))
        # 20% 从无 analysis 的选（更接近真实 short-answer 场景）
        remaining = limit - len(selected)
        if remaining > 0 and without_analysis:
            selected.extend(random.sample(without_analysis, min(remaining, len(without_analysis))))

        for item in selected:
            query = _make_rag_query(item.get("prompt", ""), item.get("answer_option", []))
            expected_answer = _make_expected_answer(item)
            keywords = _extract_keywords(item)

            samples.append({
                "query": query[:300],
                "expected_answer": expected_answer[:500],
                "expected_keywords": keywords,
                "relevant_doc_ids": [],  # K-12 题库不映射到 KB 文档
                "category": f"{grade}-{subject}",
                "metadata": {
                    "grade": grade,
                    "subject": subject,
                    "task_type": item.get("task_type", ""),
                    "difficulty": item.get("difficulty", ""),
                    "knowledge_tree": item.get("knowledge_tree", ""),
                },
            })

        print(f"  {grade}/{subject}: 选取 {len(selected)}/{len(all_items)} 条")

    print(f"\n总计: {len(samples)} 条评估样本")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    print(f"已保存到 {OUTPUT_PATH}")

    return samples


if __name__ == "__main__":
    build()

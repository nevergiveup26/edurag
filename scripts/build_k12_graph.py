"""
从 K12 题库的 knowledge_tree 字段构建知识图谱

数据源: data/external/k12_question_bank/original_data/
输出: data/graph/knowledge_graph.json

每个 knowledge_tree 路径的节点按深度分配 entity_type:
  深度0 → 学科域
  深度1 → 一级知识点
  深度2 → 二级知识点
  深度3 → 三级知识点
  深度4 → 四级知识点
  深度5+ → 细分知识点

关系: 父→子，类型为 "包含"
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict, Counter
from data_processor.graph_builder import KnowledgeGraph, Entity


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(BASE_DIR, "data", "external", "k12_question_bank", "original_data")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "graph")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "knowledge_graph.json")

ENTITY_TYPE_BY_DEPTH = {
    0: "学科域",
    1: "一级知识点",
    2: "二级知识点",
    3: "三级知识点",
    4: "四级知识点",
    5: "细分知识点",
    6: "细分知识点",
    7: "细分知识点",
}


def sanitize(s: str) -> str:
    return s.strip()


def build():
    print("=" * 60)
    print("K12 知识图谱构建")
    print("=" * 60)

    # {(knowledge_tree): [{"subject": ..., "grade": ...}, ...]}
    tree_meta = defaultdict(list)
    total_questions = 0

    for grade_dir in sorted(os.listdir(SOURCE_DIR)):
        grade_path = os.path.join(SOURCE_DIR, grade_dir)
        if not os.path.isdir(grade_path):
            continue

        for subject_dir in sorted(os.listdir(grade_path)):
            subject_path = os.path.join(grade_path, subject_dir)
            if not os.path.isdir(subject_path):
                continue

            for fname in sorted(os.listdir(subject_path)):
                if not fname.endswith(".jsonl"):
                    continue
                fp = os.path.join(subject_path, fname)
                if os.path.getsize(fp) == 0:
                    continue

                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        total_questions += 1
                        tree = d.get("knowledge_tree", "").strip()
                        if not tree:
                            continue
                        subj = d.get("task_subject", subject_dir)
                        grd = d.get("task_grade", grade_dir)
                        tree_meta[tree].append({"subject": subj, "grade": grd})

    print(f"总题目数: {total_questions}")
    print(f"唯一知识树路径: {len(tree_meta)}")

    # Build graph
    graph = KnowledgeGraph()
    node_subjects = {}  # full_path → set of subjects
    node_grades = {}    # full_path → set of grades
    entity_depth = {}   # full_path → depth

    for tree, metas in tree_meta.items():
        parts = [sanitize(p) for p in tree.split("-") if sanitize(p)]
        if not parts:
            continue

        subjects = set()
        grades = set()
        for m in metas:
            if m["subject"]:
                subjects.add(m["subject"])
            if m["grade"]:
                grades.add(m["grade"])

        # Build hierarchical path names
        for depth, part in enumerate(parts):
            full_path = "-".join(parts[:depth + 1])
            entity_type = ENTITY_TYPE_BY_DEPTH.get(depth, "细分知识点")

            if full_path not in graph.entities:
                entity = Entity(
                    name=full_path,
                    entity_type=entity_type,
                    subject="",
                    grade="",
                    description="",
                    display_name=part,
                )
                graph.add_entity(entity)
                entity_depth[full_path] = depth
                node_subjects[full_path] = set()
                node_grades[full_path] = set()

            node_subjects[full_path] |= subjects
            node_grades[full_path] |= grades

            # Relation: parent → child
            if depth > 0:
                parent_path = "-".join(parts[:depth])
                if parent_path in graph.entities:
                    # Avoid duplicate relations
                    existing = graph.adjacency.get(parent_path, [])
                    if not any(t == full_path for t, _, _ in existing):
                        graph.add_relation(parent_path, full_path, "包含", weight=1.0)

    # Post-process: set subject/grade on entities
    for name, entity in graph.entities.items():
        subs = node_subjects.get(name, set())
        grds = node_grades.get(name, set())
        entity.subject = "、".join(sorted(subs)) if subs else ""
        entity.grade = "、".join(sorted(grds)) if grds else ""

    # Stats
    type_dist = Counter(e.entity_type for e in graph.entities.values())
    subj_dist = Counter()
    for e in graph.entities.values():
        for s in node_subjects.get(e.name, set()):
            subj_dist[s] += 1

    print(f"\n图谱统计:")
    print(f"  实体数: {graph.entity_count}")
    print(f"  关系数: {graph.relation_count}")
    print(f"  实体类型分布: {dict(type_dist)}")
    print(f"  学科分布: {dict(subj_dist)}")

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    graph.save(OUTPUT_FILE)
    print(f"\n知识图谱已保存: {OUTPUT_FILE}")

    # Also save a stats summary for quick reference
    stats_file = os.path.join(OUTPUT_DIR, "k12_graph_stats.json")
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump({
            "entity_count": graph.entity_count,
            "relation_count": graph.relation_count,
            "entity_types": dict(type_dist),
            "subject_distribution": {k: v for k, v in subj_dist.most_common()},
        }, f, ensure_ascii=False, indent=2)

    return graph


if __name__ == "__main__":
    build()

"""
将 chunks_index.json (727MB JSON 数组) 迁移为 chunks_index.jsonl (逐行 JSON)
利用 JSON pretty-print 缩进格式，按行解析，内存友好。
"""
import json
import os
import time

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
JSON_FILE = os.path.join(BASE_DIR, "data", "chunks_index.json")
JSONL_FILE = os.path.join(BASE_DIR, "data", "chunks_index.jsonl")


def migrate():
    if not os.path.exists(JSON_FILE):
        print("❌ JSON 文件不存在")
        return

    if os.path.exists(JSONL_FILE) and os.path.getsize(JSONL_FILE) > 100:
        print("⚠️ JSONL 文件已存在，跳过迁移")
        return

    size_mb = os.path.getsize(JSON_FILE) / 1024 / 1024
    print(f"迁移 JSON → JSONL ({size_mb:.0f} MB)")
    print("使用行级解析...")

    t_start = time.time()
    count = 0
    lines_buf = []
    in_object = False

    with open(JSON_FILE, "r", encoding="utf-8") as fin, \
         open(JSONL_FILE, "w", encoding="utf-8") as fout:

        for line in fin:
            stripped = line.rstrip()

            # 跳过数组开头/结尾
            if stripped.strip() in ('[', ']', ''):
                continue

            # 检测对象开始: "  {" (2空格缩进)
            if not in_object and stripped.lstrip().startswith('{'):
                in_object = True
                lines_buf = [stripped]
                continue

            if in_object:
                # 去掉尾部逗号（收集阶段不去，最终解析时处理）
                lines_buf.append(stripped)

                # 检测对象结束: 精确匹配 "  }" 或 "  },"（恰好2空格 = 顶层对象闭合）
                s = stripped.rstrip()
                if s == '  }' or s == '  },':
                    in_object = False
                    # 去掉对象末尾的逗号
                    if lines_buf[-1].rstrip().endswith(','):
                        lines_buf[-1] = lines_buf[-1].rstrip()[:-1]

                    obj_text = "\n".join(lines_buf)
                    lines_buf = []

                    try:
                        obj = json.loads(obj_text)
                        fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                        count += 1

                        if count % 5000 == 0:
                            elapsed = time.time() - t_start
                            pct = fin.tell() / os.path.getsize(JSON_FILE) * 100
                            print(f"  {count} 条 ({pct:.0f}%) | {elapsed:.0f}s")
                    except json.JSONDecodeError as e:
                        print(f"  ⚠️ 解析失败 #{count+1}: {e}")

    elapsed = time.time() - t_start
    jsonl_size = os.path.getsize(JSONL_FILE) / 1024 / 1024 if os.path.exists(JSONL_FILE) else 0
    print(f"\n{'='*60}")
    print(f"✅ 迁移完成！")
    print(f"   条目数: {count}")
    print(f"   耗时: {elapsed:.0f} 秒")
    print(f"   JSONL 大小: {jsonl_size:.0f} MB")
    print(f"{'='*60}")

    # 验证
    print("\n验证 JSONL 文件...")
    verify_count = sum(1 for line in open(JSONL_FILE, "r", encoding="utf-8") if line.strip())
    print(f"  JSONL 行数: {verify_count}")
    if verify_count == count:
        print("  ✅ 验证通过！")
    else:
        print(f"  ⚠️ 行数不匹配！预期 {count}，实际 {verify_count}")


if __name__ == "__main__":
    migrate()

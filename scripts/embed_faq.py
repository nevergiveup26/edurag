"""对FAQ批量向量化，更新embedding字段"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.mysql_db import MySQLDB
from data_processor.vectorizer import Vectorizer

db = MySQLDB()
rows = db.query("SELECT id, question FROM faq")
ids = [r["id"] for r in rows]
questions = [r["question"] for r in rows]
print(f"共 {len(rows)} 条FAQ，批量向量化中...")

vectorizer = Vectorizer()
embeddings = vectorizer.embed(questions)

for i, (faq_id, emb) in enumerate(zip(ids, embeddings)):
    emb_json = json.dumps(emb)
    db.execute("UPDATE faq SET embedding = %s WHERE id = %s", (emb_json, faq_id))
    print(f"  [{i+1}/{len(rows)}] ✅ {questions[i][:40]}...")

print("完成")

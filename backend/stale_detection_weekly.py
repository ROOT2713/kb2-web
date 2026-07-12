#!/usr/bin/env python3
"""KB2 知识库 OKF stale 检测周报"""
import sys
sys.path.insert(0, '.')

from app.services.stale_detection import detect_stale_documents, get_stale_summary
from app.models.database import SessionLocal

db = SessionLocal()

# Step 1: Run stale detection
result = detect_stale_documents(db, max_days=90)
print(f"STEP1|检查完成: {result['total_checked']} 文档, {result['stale_count']} 个 stale")

# Step 2: Get summary
s = get_stale_summary(db)
print(f"STEP2|活跃:{s['active']} 过期:{s['stale']} 已替代:{s['superseded']} 总计:{s['total']}")

# Step 3: List stale docs (if any)
if result['stale_count'] > 0:
    r = detect_stale_documents(db, max_days=90, dry_run=True)
    print(f"STEP3|Stale 文档列表 (前10):")
    for d in r['stale_docs'][:10]:
        print(f"  - {d['title'][:30]} | {d['stale_reason']}")
else:
    print("STEP3|无 stale 文档")

db.close()

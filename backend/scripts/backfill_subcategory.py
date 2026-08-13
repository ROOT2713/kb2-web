"""Backfill subcategory for existing documents based on category_rules.

Usage: python scripts/backfill_subcategory.py

Scans all documents with a non-empty category but empty subcategory,
infers subcategory from title/filename/bank/category/doc_type,
and updates the subcategory column.
"""
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.database import SessionLocal
from app.models.document import Document
from app.services.category_rules import infer_subcategory


def main():
    db = SessionLocal()
    try:
        # Find docs with category but empty subcategory
        docs = db.query(Document).filter(
            Document.category != "",
            Document.category.isnot(None),
            (Document.subcategory == "") | Document.subcategory.is_(None),
        ).all()
        
        total = len(docs)
        updated = 0
        skipped = 0
        
        for d in docs:
            subcat = infer_subcategory(
                title=d.title or "",
                filename=d.filename or "",
                bank=d.bank or "",
                category=d.category or "",
                doc_type=d.doc_type or "",
            )
            if subcat:
                d.subcategory = subcat
                updated += 1
            else:
                skipped += 1
        
        db.commit()
        print(f"总文档: {total}")
        print(f"已更新 subcategory: {updated}")
        print(f"未能推断 (留空): {skipped}")
        
        # Show distribution
        if updated > 0:
            counts = db.query(Document.subcategory, db.func.count(Document.doc_id)).filter(
                Document.subcategory != "",
                Document.subcategory.isnot(None),
            ).group_by(Document.subcategory).order_by(db.func.count(Document.doc_id).desc()).all()
            print("\n子分类分布:")
            for sc, cnt in counts:
                print(f"  {sc}: {cnt}")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()

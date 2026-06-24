"""Backfill published_date and geo_scope for existing documents.

Inference rules:
- geo_scope: standard number prefix → national/provincial/city/enterprise
- published_date: extract from title (year patterns) → estimated publication date

Usage: python3 scripts/backfill_doc_metadata.py
"""

import re
import sys
sys.path.insert(0, '.')

from sqlalchemy import text as sa_text
from app.models.database import SessionLocal


# ── geo_scope inference rules ──
_GEO_PATTERNS = [
    (re.compile(r'^GB\b'), 'national'),
    (re.compile(r'\bGB[ /]'), 'national'),
    (re.compile(r'\bGB/T\b'), 'national'),
    (re.compile(r'\bDB\d{2}/T\b'), 'provincial'),
    (re.compile(r'\bDB\d{2}\b'), 'provincial'),
    (re.compile(r'\bDG\b'), 'city'),
    (re.compile(r'\bQ/\b'), 'enterprise'),
    (re.compile(r'\bISO\b'), 'national'),
    (re.compile(r'\bYD/T\b'), 'national'),
    (re.compile(r'\bSJ/T\b'), 'national'),
    (re.compile(r'\bGA\d+\b'), 'national'),
    (re.compile(r'\bHJ\d+\b'), 'national'),
    (re.compile(r'\bCJJ\d+\b'), 'national'),
]

# ── year inference rules ──
_DATE_PATTERNS = [
    re.compile(r'(20\d{2})[年-]'),
    re.compile(r'\b(20\d{2})\b'),
]


def infer_geo_scope(title: str) -> str | None:
    if not title:
        return None
    for pat, scope in _GEO_PATTERNS:
        if pat.search(title):
            return scope
    return None


def infer_published_date(title: str) -> str | None:
    """Extract year from title, return YYYY-01-01 or None."""
    if not title:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(title)
        if m:
            year = m.group(1)
            return f"{year}-01-01"
    return None


def main():
    db = SessionLocal()
    try:
        # Get all documents
        rows = db.execute(
            sa_text("SELECT doc_id, title, published_date, geo_scope FROM documents")
        ).fetchall()
        print(f"Total documents: {len(rows)}")

        updated_pub = 0
        updated_geo = 0

        for row in rows:
            doc_id, title, pub_date, geo = row
            updates = []

            # published_date: only backfill if NULL
            if pub_date is None:
                inferred = infer_published_date(title)
                if inferred:
                    updates.append(f"published_date='{inferred}'")

            # geo_scope: only backfill if NULL
            if geo is None:
                inferred = infer_geo_scope(title)
                if inferred:
                    updates.append(f"geo_scope='{inferred}'")

            if updates:
                sql = f"UPDATE documents SET {', '.join(updates)} WHERE doc_id=:did"
                db.execute(sa_text(sql), {"did": doc_id})
                if any("published_date" in u for u in updates):
                    updated_pub += 1
                if any("geo_scope" in u for u in updates):
                    updated_geo += 1

        db.commit()
        print(f"  published_date backfilled: {updated_pub}")
        print(f"  geo_scope backfilled:      {updated_geo}")

        # Show sample
        samples = db.execute(
            sa_text(
                "SELECT doc_id, title, published_date, geo_scope FROM documents "
                "WHERE published_date IS NOT NULL OR geo_scope IS NOT NULL "
                "ORDER BY published_date DESC LIMIT 10"
            )
        ).fetchall()
        print(f"\nSample backfills (top 10 by date):")
        for s in samples[:5]:
            print(f"  {s[0][:8]} pub={s[2]} geo={s[3]}  {s[1][:50]}")

    finally:
        db.close()


if __name__ == "__main__":
    main()

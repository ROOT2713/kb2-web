#!/usr/bin/env python3
"""Dry-run diff report for V1 meta.db vs V2 kb.db table/checklist content.

This script is read-only. It opens SQLite databases with mode=ro and never writes.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_V1 = "/home/ubuntu/kb-web/meta.db"
DEFAULT_V2 = "/home/ubuntu/kb-web/data/kb.db"
TABLE_LIKE_SQL = """
parent_text LIKE '%|%'
OR parent_text LIKE '%<table%'
OR parent_text LIKE '%Sheet:%'
OR parent_text LIKE '%检查项%'
OR parent_text LIKE '%检查要求%'
OR parent_text LIKE '%检查方法%'
OR parent_text LIKE '%核查力度%'
"""


def connect_ro(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def detect_schema(conn: sqlite3.Connection) -> Dict[str, str]:
    if table_exists(conn, "documents"):
        docs = "documents"
    elif table_exists(conn, "doc_meta"):
        docs = "doc_meta"
    else:
        raise RuntimeError("no documents/doc_meta table found")
    if not table_exists(conn, "parent_chunks"):
        raise RuntimeError("no parent_chunks table found")
    return {"docs": docs, "chunks": "parent_chunks"}


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def pick(cols: set[str], *names: str, default: str = "''") -> str:
    for name in names:
        if name in cols:
            return name
    return default


def fetch_docs(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    schema = detect_schema(conn)
    table = schema["docs"]
    cols = columns(conn, table)
    doc_id = pick(cols, "doc_id", "id")
    title = pick(cols, "title", "filename")
    bank = pick(cols, "bank", default="'general'")
    doc_type = pick(cols, "doc_type", default="'generic'")
    filename = pick(cols, "filename", default="''")
    rows = conn.execute(
        f"SELECT {doc_id} AS doc_id, {title} AS title, {bank} AS bank, "
        f"{doc_type} AS doc_type, {filename} AS filename FROM {table}"
    ).fetchall()
    return [dict(r) for r in rows]


def group_counts(conn: sqlite3.Connection, field: str) -> Dict[str, int]:
    schema = detect_schema(conn)
    table = schema["docs"]
    cols = columns(conn, table)
    if field not in cols:
        return {}
    return {str(r[0] or ""): int(r[1]) for r in conn.execute(
        f"SELECT {field}, COUNT(*) FROM {table} GROUP BY {field} ORDER BY COUNT(*) DESC"
    ).fetchall()}


def chunk_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    return {str(r[0]): int(r[1]) for r in conn.execute(
        "SELECT doc_id, COUNT(*) FROM parent_chunks GROUP BY doc_id"
    ).fetchall()}


def table_like_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    return {str(r[0]): int(r[1]) for r in conn.execute(
        f"SELECT doc_id, COUNT(*) FROM parent_chunks WHERE {TABLE_LIKE_SQL} GROUP BY doc_id"
    ).fetchall()}


def db_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    docs = fetch_docs(conn)
    chunks_total = conn.execute("SELECT COUNT(*) FROM parent_chunks").fetchone()[0]
    table_like_total = conn.execute(
        f"SELECT COUNT(*) FROM parent_chunks WHERE {TABLE_LIKE_SQL}"
    ).fetchone()[0]
    excel_docs = [d for d in docs if str(d.get("filename") or d.get("title") or "").lower().endswith((".xlsx", ".xls"))]
    return {
        "documents_total": len(docs),
        "bank_counts": group_counts(conn, "bank"),
        "doc_type_counts": group_counts(conn, "doc_type"),
        "parent_chunks_total": int(chunks_total),
        "table_like_chunks_total": int(table_like_total),
        "excel_docs": excel_docs,
    }


def build_report(v1_path: str, v2_path: str) -> Dict[str, Any]:
    with connect_ro(v1_path) as v1, connect_ro(v2_path) as v2:
        v1_docs = fetch_docs(v1)
        v2_docs = fetch_docs(v2)
        v1_by_id = {d["doc_id"]: d for d in v1_docs}
        v2_by_id = {d["doc_id"]: d for d in v2_docs}
        v1_ids = set(v1_by_id)
        v2_ids = set(v2_by_id)
        v1_chunks = chunk_counts(v1)
        v2_chunks = chunk_counts(v2)
        v1_tables = table_like_counts(v1)
        v2_tables = table_like_counts(v2)
        chunk_diffs = []
        for doc_id in sorted(v1_ids | v2_ids):
            c1 = v1_chunks.get(doc_id, 0)
            c2 = v2_chunks.get(doc_id, 0)
            t1 = v1_tables.get(doc_id, 0)
            t2 = v2_tables.get(doc_id, 0)
            if c1 != c2 or t1 != t2:
                meta = v1_by_id.get(doc_id) or v2_by_id.get(doc_id) or {"doc_id": doc_id}
                chunk_diffs.append({
                    "doc_id": doc_id,
                    "title": meta.get("title", ""),
                    "bank": meta.get("bank", ""),
                    "doc_type": meta.get("doc_type", ""),
                    "v1_chunks": c1,
                    "v2_chunks": c2,
                    "v1_table_like": t1,
                    "v2_table_like": t2,
                    "chunk_delta": c2 - c1,
                    "table_like_delta": t2 - t1,
                })
        chunk_diffs.sort(key=lambda d: (abs(d["chunk_delta"]) + abs(d["table_like_delta"])), reverse=True)
        return {
            "paths": {"v1": v1_path, "v2": v2_path},
            "v1": db_summary(v1),
            "v2": db_summary(v2),
            "diff": {
                "v1_only_docs": [v1_by_id[i] for i in sorted(v1_ids - v2_ids)],
                "v2_only_docs": [v2_by_id[i] for i in sorted(v2_ids - v1_ids)],
                "chunk_count_diffs": chunk_diffs[:20],
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1", default=DEFAULT_V1)
    parser.add_argument("--v2", default=DEFAULT_V2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report(args.v1, args.v2)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"V1 docs={report['v1']['documents_total']} chunks={report['v1']['parent_chunks_total']} table_like={report['v1']['table_like_chunks_total']}")
        print(f"V2 docs={report['v2']['documents_total']} chunks={report['v2']['parent_chunks_total']} table_like={report['v2']['table_like_chunks_total']}")
        print(f"V1-only docs={len(report['diff']['v1_only_docs'])} V2-only docs={len(report['diff']['v2_only_docs'])}")
        print("Top chunk/table diffs:")
        for row in report['diff']['chunk_count_diffs'][:10]:
            print(f"- {row['doc_id']} {row['title'][:60]} chunks {row['v1_chunks']}->{row['v2_chunks']} table {row['v1_table_like']}->{row['v2_table_like']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

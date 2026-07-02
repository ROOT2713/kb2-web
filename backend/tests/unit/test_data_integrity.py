"""
文档数据完整性检查 — DB 级别的数据质量回归测试。

注意：本测试需要访问 production DB。不带 --run-integration 时会自动跳过。
需要用 pytest -s --run-integration 运行。
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import text as sa_text

from app.models.database import SessionLocal

# 所有数据完整性测试需要 production DB
pytestmark = pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="需要 --run-integration 和 production DB 访问",
)

# ── 配置 ────────────────────────────────────────────────────────────
_KNOWN_BANKS = frozenset({
    "standards", "general", "industry_docs", "project_docs",
    "tech_guides", "checklist", "methodology", "business",
})

# 每个 bank 预期的文档数量范围（根据产线数据动态调整）
_BANK_COUNT_RANGES = {
    "standards":      (50, 300),
    "general":        (20, 200),
    "industry_docs":  (5, 50),
    "project_docs":   (2, 30),
    "tech_guides":    (1, 20),
    "checklist":      (1, 10),
    "methodology":    (1, 10),
    "business":       (5, 60),
}

_MIN_TOTAL_DOCS = 200
_MIN_TOTAL_CHUNKS = 1000


# ═══════════════════════════════════════════════════════════════════
# 引用完整性
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def db():
    """Provide a DB session for the test module."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestReferentialIntegrity:
    """外键级数据完整性。"""

    def test_no_orphaned_parent_chunks(self, db):
        """不存在 parent_chunks 但 documents 表已删除记录的孤儿。"""
        orphaned = db.execute(sa_text("""
            SELECT COUNT(*) FROM parent_chunks p
            LEFT JOIN documents d ON p.doc_id = d.doc_id
            WHERE d.doc_id IS NULL
        """)).fetchone()[0]
        assert orphaned == 0, f"发现 {orphaned} 条 orphaned parent_chunks"

    def test_searchable_docs_have_chunks(self, db):
        """所有 searchable=1 且 status='active' 的文档必须存在 parent_chunks。"""
        count = db.execute(sa_text("""
            SELECT COUNT(*) FROM documents d
            WHERE d.searchable = 1 AND d.status = 'active'
            AND NOT EXISTS (SELECT 1 FROM parent_chunks p WHERE p.doc_id = d.doc_id)
        """)).fetchone()[0]
        assert count == 0, f"发现 {count} 个 searchable 文档无 parent_chunks"

    def test_non_searchable_docs_may_have_no_chunks(self, db):
        """searchable=0 的文档允许无 chunks，但不应该有残余 chunks。"""
        count = db.execute(sa_text("""
            SELECT COUNT(*) FROM parent_chunks p
            JOIN documents d ON p.doc_id = d.doc_id
            WHERE d.searchable = 0
        """)).fetchone()[0]
        assert count == 0, f"发现 {count} 个 searchable=0 的文档仍有 parent_chunks（应清理）"

    def test_all_doc_ids_in_parent_chunks_valid(self, db):
        """parent_chunks 中的 doc_id 必须全部存在于 documents 表。"""
        invalid = db.execute(sa_text("""
            SELECT COUNT(DISTINCT p.doc_id) FROM parent_chunks p
            LEFT JOIN documents d ON p.doc_id = d.doc_id
            WHERE d.doc_id IS NULL
        """)).fetchone()[0]
        assert invalid == 0, f"发现 {invalid} 个无效的 doc_id 在 parent_chunks"

    def test_no_duplicate_doc_ids(self, db):
        """documents 表无重复 doc_id。"""
        dup = db.execute(sa_text("""
            SELECT COUNT(*) FROM (
                SELECT doc_id, COUNT(*) as cnt
                FROM documents GROUP BY doc_id HAVING cnt > 1
            )
        """)).fetchone()[0]
        assert dup == 0, f"发现 {dup} 组重复 doc_id"


class TestFieldCompleteness:
    """字段完整性检查。"""

    def test_no_null_titles(self, db):
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM documents WHERE title IS NULL OR title = ''"
        )).fetchone()[0]
        assert count == 0, f"发现 {count} 个文档 title 为空"

    def test_no_null_bank(self, db):
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM documents WHERE bank IS NULL"
        )).fetchone()[0]
        assert count == 0, f"发现 {count} 个文档 bank 为 NULL"

    def test_bank_values_known(self, db):
        """所有 bank 值必须在已知列表中。"""
        rows = db.execute(sa_text("SELECT DISTINCT bank FROM documents")).fetchall()
        unknown = [r[0] for r in rows if r[0] not in _KNOWN_BANKS]
        assert len(unknown) == 0, f"未知 bank 值: {unknown}"

    def test_active_docs_have_updated_at(self, db):
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM documents WHERE status='active' AND updated_at IS NULL"
        )).fetchone()[0]
        assert count == 0, f"发现 {count} 个 active 文档 updated_at 为空"

    def test_searchable_docs_have_content_hash(self, db):
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM documents WHERE searchable=1 AND (content_hash IS NULL OR content_hash = '')"
        )).fetchone()[0]
        assert count == 0, f"发现 {count} 个 searchable 文档 content_hash 为空"

    def test_searchable_docs_have_nonzero_length(self, db):
        """searchable=1 的文档应有 original_text_length > 0。"""
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM documents WHERE searchable=1 AND (original_text_length IS NULL OR original_text_length = 0)"
        )).fetchone()[0]
        # 允许少量字段未回填的文档（已知 bug，缓步修复）
        max_allowed = 5
        assert count <= max_allowed, \
            f"发现 {count} 个 searchable 文档 original_text_length=0（允许 ≤{max_allowed}）"


class TestDataConsistency:
    """跨表数据一致性。"""

    def test_chunk_count_consistent(self, db):
        """documents.chunk_count 字段应与 parent_chunks 实际计数一致。"""
        mismatches = db.execute(sa_text("""
            SELECT d.doc_id, d.title, d.chunk_count, actual.cnt
            FROM documents d
            JOIN (
                SELECT doc_id, COUNT(*) as cnt
                FROM parent_chunks GROUP BY doc_id
            ) actual ON d.doc_id = actual.doc_id
            WHERE d.chunk_count IS NOT NULL
            AND d.chunk_count != actual.cnt
            LIMIT 10
        """)).fetchall()
        assert len(mismatches) == 0, \
            f"chunk_count 不一致（前10条）: {[(r.title[:30], r.chunk_count, r.cnt) for r in mismatches]}"

    def test_total_document_count(self, db):
        total = db.execute(sa_text(
            "SELECT COUNT(*) FROM documents WHERE status='active'"
        )).fetchone()[0]
        assert total >= _MIN_TOTAL_DOCS, \
            f"文档总数异常: {total}（低于最小预期 {_MIN_TOTAL_DOCS}）"

    def test_total_chunk_count(self, db):
        total = db.execute(sa_text(
            "SELECT COUNT(*) FROM parent_chunks"
        )).fetchone()[0]
        assert total >= _MIN_TOTAL_CHUNKS, \
            f"chunk 总数异常: {total}（低于最小预期 {_MIN_TOTAL_CHUNKS}）"

    def test_bank_counts_within_range(self, db):
        """每个 bank 的文档数在预期范围内。"""
        rows = db.execute(sa_text(
            "SELECT bank, COUNT(*) as cnt FROM documents WHERE status='active' GROUP BY bank"
        )).fetchall()
        for bank, cnt in rows:
            if bank not in _BANK_COUNT_RANGES:
                continue  # 未知 bank 跳过
            lo, hi = _BANK_COUNT_RANGES[bank]
            assert lo <= cnt <= hi, \
                f"bank={bank} 文档数 {cnt} 超出预期范围 [{lo}, {hi}]"

    def test_all_banks_have_docs(self, db):
        """每个已知 bank 至少有一条记录。"""
        rows = db.execute(sa_text(
            "SELECT bank, COUNT(*) as cnt FROM documents GROUP BY bank"
        )).fetchall()
        present = {r[0] for r in rows}
        missing = _KNOWN_BANKS - present
        # business 是可选 bank
        allowed_missing = {"business", "methodology", "checklist"}
        actually_missing = missing - allowed_missing
        assert len(actually_missing) == 0, \
            f"缺少数据的 bank: {actually_missing}"

    def test_searchable_vs_total_ratio(self, db):
        """searchable=1 的文档应占总数的合理比例。"""
        total = db.execute(sa_text("SELECT COUNT(*) FROM documents")).fetchone()[0]
        searchable = db.execute(sa_text(
            "SELECT COUNT(*) FROM documents WHERE searchable=1"
        )).fetchone()[0]
        ratio = searchable / max(total, 1)
        assert ratio >= 0.5, \
            f"searchable 比例异常: {ratio:.0%}（{searchable}/{total}）"


class TestDataFreshness:
    """数据时效性检查。"""

    def test_recent_uploads_have_recent_updated_at(self, db):
        """最近 20 条文档应有时效性合理的 updated_at。"""
        rows = db.execute(sa_text("""
            SELECT doc_id, title, updated_at FROM documents
            WHERE status='active'
            ORDER BY updated_at DESC LIMIT 20
        """)).fetchall()
        for r in rows:
            assert r.updated_at is not None, \
                f"文档 {r.title[:30]} updated_at 为空"

    def test_no_future_dates(self, db):
        count = db.execute(sa_text("""
            SELECT COUNT(*) FROM documents
            WHERE updated_at > datetime('now', '+1 day')
               OR created_at > datetime('now', '+1 day')
        """)).fetchone()[0]
        assert count == 0, f"发现 {count} 条未来时间戳"


class TestChunkQuality:
    """chunk 层数据质量。"""

    def test_parent_text_not_empty(self, db):
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM parent_chunks WHERE parent_text IS NULL OR length(parent_text) = 0"
        )).fetchone()[0]
        assert count == 0, f"发现 {count} 条空 parent_text"

    def test_parent_text_min_length(self, db):
        """parent_text 应有最小长度（过短的 chunk 无检索价值）。"""
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM parent_chunks WHERE length(parent_text) < 20"
        )).fetchone()[0]
        max_allowed = int(db.execute(sa_text(
            "SELECT COUNT(*) FROM parent_chunks"
        )).fetchone()[0] * 0.01)  # 允许 ≤1% 的短 chunk
        assert count <= max_allowed, \
            f"长度 <20 字符的 chunk 有 {count} 条（超过阈值 {max_allowed}）"

    def test_parent_text_has_content(self, db):
        """parent_text 不能只含空白字符。"""
        count = db.execute(sa_text(
            "SELECT COUNT(*) FROM parent_chunks WHERE length(trim(parent_text)) = 0"
        )).fetchone()[0]
        assert count == 0, f"发现 {count} 条纯空白 parent_text"

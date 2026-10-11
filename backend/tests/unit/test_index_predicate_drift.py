"""check_index_predicate_drift 纯函数单测（无需 DB）。

承重点：代码谓词与索引谓词对齐 = 部分索引不静默失效的前提。
本文件同时把「当前代码谓词」钉住（test_extract_code_predicate_live_repo），
若 vector_repo.py 的检索 WHERE 被改动，测试先红 —— 提醒同步索引与巡检基线。
"""
import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
sys.path.insert(0, SCRIPTS_DIR)

import check_index_predicate_drift as drift  # noqa: E402
import create_partial_vector_indexes as ddl  # noqa: E402

# 真实 indexdef（取自 2026-10-12 live 库 pg_indexes）
REAL_GENERAL = (
    "CREATE INDEX idx_vc_kb_general_pr ON public.vector_chunks USING hnsw "
    "(embedding vector_cosine_ops) WITH (m='24', ef_construction='200') "
    "WHERE ((bank = 'kb_general'::text) AND ((metadata ->> 'registry'::text) = '1'::text))"
)
REAL_STANDARD = (
    "CREATE INDEX idx_vc_kb_standard_pr ON public.vector_chunks USING hnsw "
    "(embedding vector_cosine_ops) WITH (m='24', ef_construction='200') "
    "WHERE ((bank = 'kb_standard'::text) AND ((metadata ->> 'registry'::text) = '1'::text))"
)

ALIGNED_CODE = {"registry_key": "registry", "registry_value": "1", "bank_filter": True}


def _idx(name, bank, reg_key="registry", reg_val="1"):
    return {"name": name, "bank": bank, "registry_key": reg_key, "registry_value": reg_val}


# ── 解析 ────────────────────────────────────────────────────────────
def test_parse_real_indexdef():
    r = drift.parse_index_def(REAL_GENERAL)
    assert r == {"name": "idx_vc_kb_general_pr", "bank": "kb_general",
                 "registry_key": "registry", "registry_value": "1"}


def test_parse_handles_concurrently_if_not_exists():
    """生成的 DDL 含 CONCURRENTLY IF NOT EXISTS，索引名不能被解析成 'IF'。"""
    r = drift.parse_index_def(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vc_kb_xhs_pr ON vector_chunks "
        "USING hnsw (embedding vector_cosine_ops) WHERE bank = 'kb_xhs' "
        "AND metadata->>'registry' = '1';"
    )
    assert r["name"] == "idx_vc_kb_xhs_pr"
    assert (r["bank"], r["registry_key"], r["registry_value"]) == ("kb_xhs", "registry", "1")


def test_extract_code_predicate_from_snippet():
    sql = "WHERE bank = $1 AND embedding IS NOT NULL AND metadata->>'registry' = '1'"
    assert drift.extract_code_predicate(sql) == ALIGNED_CODE


def test_extract_code_predicate_live_repo():
    """钉住当前代码谓词：改动 vector_repo 检索 WHERE 会让本用例先红。"""
    src = open(drift.SQL_FILE, encoding="utf-8").read()
    assert drift.extract_code_predicate(src) == ALIGNED_CODE


# ── 由构造保证的耦合（生成 DDL 的谓词 == 代码谓词）──────────────────
def test_generated_ddl_predicate_matches_code():
    src = open(drift.SQL_FILE, encoding="utf-8").read()
    code = drift.extract_code_predicate(src)
    stmts = ddl.build_sql(ddl.BANKS, code["registry_key"], code["registry_value"])
    assert len(stmts) == len(ddl.BANKS)
    for s in stmts:
        assert "IF NOT EXISTS" in s and "CONCURRENTLY" in s  # 幂等 + 零停机
        p = drift.parse_index_def(s)
        assert p["registry_key"] == code["registry_key"]
        assert p["registry_value"] == code["registry_value"]
        assert p["bank"] in ddl.BANKS


# ── 比对 ────────────────────────────────────────────────────────────
def test_aligned_reports_nothing():
    idxs = [_idx("idx_vc_kb_general_pr", "kb_general"), _idx("idx_vc_kb_standard_pr", "kb_standard")]
    probs = drift.check_drift(ALIGNED_CODE, idxs,
                              {"kb_general": 465, "kb_standard": 18889}, ddl_declared=True)
    assert probs == []


def test_registry_value_drift_is_critical():
    idxs = [_idx("idx_vc_kb_general_pr", "kb_general", reg_val="2")]  # 索引写 2、代码读 1
    probs = drift.check_drift(ALIGNED_CODE, idxs, {"kb_general": 465}, ddl_declared=True)
    assert [p.severity for p in probs] == ["CRITICAL"]
    assert "漂移" in probs[0].reason


def test_registry_key_drift_is_critical():
    idxs = [_idx("idx_vc_kb_general_pr", "kb_general", reg_key="reg")]
    probs = drift.check_drift(ALIGNED_CODE, idxs, {"kb_general": 465}, ddl_declared=True)
    assert any(p.severity == "CRITICAL" for p in probs)


def test_missing_bank_filter_in_code_is_critical():
    code = {"registry_key": "registry", "registry_value": "1", "bank_filter": False}
    probs = drift.check_drift(code, [_idx("idx_vc_kb_general_pr", "kb_general")],
                              {"kb_general": 465}, ddl_declared=True)
    assert any(p.severity == "CRITICAL" and p.subject == "code" for p in probs)


def test_bank_with_data_without_index_is_alert():
    idxs = [_idx("idx_vc_kb_general_pr", "kb_general")]
    probs = drift.check_drift(ALIGNED_CODE, idxs,
                              {"kb_general": 465, "kb_project": 117}, ddl_declared=True)
    docs = [p for p in probs if p.severity == "ALERT"]
    assert len(docs) == 1 and docs[0].subject == "kb_project"


def test_stale_index_is_info_only():
    idxs = [_idx("idx_vc_kb_general_pr", "kb_general"), _idx("idx_vc_kb_ghost_pr", "kb_ghost")]
    probs = drift.check_drift(ALIGNED_CODE, idxs, {"kb_general": 465}, ddl_declared=True)
    assert [p.severity for p in probs] == ["INFO"]
    assert probs[0].subject == "kb_ghost"


def test_missing_ddl_source_is_warn():
    probs = drift.check_drift(ALIGNED_CODE, [_idx("idx_vc_kb_general_pr", "kb_general")],
                              {"kb_general": 465}, ddl_declared=False)
    assert [p.severity for p in probs] == ["WARN"]


def test_index_without_registry_predicate_is_critical():
    idxs = [{"name": "idx_vc_weird_pr", "bank": "kb_general",
             "registry_key": None, "registry_value": None}]
    probs = drift.check_drift(ALIGNED_CODE, idxs, {"kb_general": 465}, ddl_declared=True)
    assert any(p.severity == "CRITICAL" for p in probs)


# ── 突变核验：真 indexdef 翻值必被检出 ──────────────────────────────
@pytest.mark.parametrize("mutated_val", ["2", "0", "true"])
def test_mutation_flip_registry_value_detected(mutated_val):
    mutated = REAL_STANDARD.replace("'registry'::text) = '1'::text", f"'registry'::text) = '{mutated_val}'::text")
    assert mutated != REAL_STANDARD
    idxs = [drift.parse_index_def(mutated)]
    probs = drift.check_drift(ALIGNED_CODE, idxs, {"kb_standard": 18889}, ddl_declared=True)
    assert any(p.severity == "CRITICAL" for p in probs)


# ── DDL 来源检查自身的守卫（防 2026-10-12 踩到的假阳性复发）─────────
def test_ddl_source_found_in_repo():
    """真实仓库有 create_partial_vector_indexes.py 声明，5 名应全命中。"""
    assert drift.ddl_declares_partial_indexes(ddl.BANKS and list(ddl.BANK_INDEX_NAMES.values()))


def test_ddl_source_unknown_index_is_false():
    """不存在的索引名不得被判为『已声明』。"""
    assert drift.ddl_declares_partial_indexes(["idx_vc_kb_nonexistent_pr"]) is False


def test_ddl_source_ignores_test_files():
    """测试文件（backend/tests/）里的 CREATE INDEX 字样不得算作 DDL 来源。"""
    srcs = list(drift._ddl_source_files(drift.REPO_ROOT))
    assert not any("/tests/" in p for p in srcs)
    assert not any("/docs/" in p for p in srcs)

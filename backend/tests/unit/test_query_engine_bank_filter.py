"""query_engine 检索结果 bank 过滤的回归锁（2026-10-07）。

缺陷背景
--------
``/api/query`` 组装 ``sources`` 时按请求 bank 过滤结果：读 ``documents.bank``
列值，用一张 legacy→业务键 映射表把它映射回业务键再比对。该映射表（原内联在
``_build_search_context``）**缺** ``"project_docs"→"project"`` 与
``"traffic"→"industry"`` ⇒ 请求 ``bank='project'`` 时 3 篇
``active∧searchable=1`` 的项目文档（``documents.bank='project_docs'``）
全部被 ``continue`` 丢弃 → API 恒返 0 sources。

实证（2026-10-07，真实服务）：
  - BM25 检索层**已命中**它们：``[BM25-DEBUG] bank=project hits=30
    doc_ids=['4770253c','90241f1a','78bdaf5e']``；
  - 但 ``/api/query bank=project`` 返回 ``sources=[]``（4 次一致）；
  - 补映射后同一查询 → 3 篇可见（真实数据模拟，其余 bank 不变）。

该缺陷暴露了**两张并行 bank 映射表漂移**的隐患：``retrieval.LEGACY_BANK_TO_HS``
（含 project_docs/traffic）与 query_engine 内联表（漏配）。本文件同时钉住二者一致。

本文件钉四条：
  ① 已知 documents.bank 取值必须全被映射覆盖（防再漏）；
  ② 映射口径必须与 retrieval 的单一来源一致（防两表漂移）；
  ③ ``project_docs`` / ``traffic`` 两处历史缺陷点显式钉住；
  ④ 过滤纯函数 ``bank_visible_for_request`` 各分支行为。

【密封性】不依赖生产环境：涉及 ``BANKS`` 的断言用 ``FIXTURE_BANKS`` 显式构造
（``_hermetic_banks`` 自动 fixture）；``TestLiveDatabaseCoverage`` 需真实库，
缺失时 skip。
"""
from __future__ import annotations

import os

import pytest

from app.api import query_engine
from app.api.query_engine import (LEGACY_BANK_TO_BIZKEY,
                                  bank_visible_for_request)
from app.services import retrieval

# 实测取值（kb.db documents.bank distinct，去 'skip'）——与 test_bank_group_visibility 同源
OBSERVED_DB_BANK_VALUES = [
    "standards", "industry", "general", "咨询",
    "kb_xhs", "industry_docs", "project_docs", "traffic",
]

# 与生产 banks.json 逐字对齐的测试夹具（密封：不读外部文件）。
FIXTURE_BANKS = {
    "all": {"name": "全部", "hindsight": None,
            "vector_banks": ["kb_standard", "kb_industry", "kb_tech", "kb_general",
                                "kb_checklist", "kb_template", "kb_xhs", "kb_project"],
            "prompt": "通用政务信息化知识库"},
    "industry": {"name": "信息化行业", "hindsight": "kb_industry",
                 "vector_banks": ["kb_standard", "kb_industry", "kb_tech",
                                     "kb_general", "kb_checklist", "kb_template"],
                 "prompt": "政务信息化行业专家"},
    "personal": {"name": "个人资讯", "hindsight": "kb_xhs",
                 "vector_banks": ["kb_xhs"], "prompt": "内容分析专家"},
    "project": {"name": "项目文档", "hindsight": "kb_project",
                "prompt": "项目管理专家"},
    "general": {"name": "综合文件", "hindsight": "kb_general",
                "prompt": "综合文件领域专家"},
}

BIZKEYS = {k for k in FIXTURE_BANKS if k != "all"}


def _targets_of(bizkey: str) -> set[str]:
    """业务键的检索范围（vector_banks 优先，退回 hindsight 单值）。"""
    cfg = FIXTURE_BANKS[bizkey]
    return set(cfg.get("vector_banks") or ([cfg["hindsight"]] if cfg.get("hindsight") else []))


@pytest.fixture(autouse=True)
def _hermetic_banks(monkeypatch):
    """把 retrieval.BANKS 换成显式夹具，使口径断言与环境配置解耦。"""
    monkeypatch.setattr(retrieval, "BANKS", dict(FIXTURE_BANKS))
    yield


# ── ③ 历史缺陷点显式钉住 ────────────────────────────────────────────
def test_regression_project_docs_and_traffic_entries_present():
    """[回归锁] project_docs→project 与 traffic→industry 必须在映射表内。

    缺任一 ⇒ 请求 bank=project 丢弃 3 篇项目文档 / bank=industry 丢弃 traffic 文档。
    """
    assert LEGACY_BANK_TO_BIZKEY.get("project_docs") == "project"
    assert LEGACY_BANK_TO_BIZKEY.get("traffic") == "industry"


# ── ④ 过滤纯函数行为 ───────────────────────────────────────────────
@pytest.mark.parametrize("doc_bank, requested, expected", [
    # 请求 all → 一律可见（除 skip）
    ("project_docs", "all", True),
    ("standards", "all", True),
    # 物理库名请求 → 不做过滤
    ("project_docs", "kb_project", True),
    # 文档 bank 值恰等于请求业务键
    ("project", "project", True),
    ("general", "general", True),
    # legacy 值经映射命中
    ("project_docs", "project", True),   # ← 本次修复点
    ("traffic", "industry", True),        # ← 本次修复点
    ("standards", "industry", True),
    ("industry_docs", "industry", True),
    ("咨询", "personal", True),
    ("kb_xhs", "personal", True),
    # 文档 bank 值缺失 → 不拦（交由后续逻辑）
    (None, "project", True),
    # legacy 值映射到别的业务键 → 不可见
    ("project_docs", "industry", False),
    ("standards", "project", False),
    ("kb_xhs", "industry", False),
    # skip → 永不可见（即便请求 all）
    ("skip", "all", False),
    ("skip", "project", False),
])
def test_bank_visible_for_request_matrix(doc_bank, requested, expected):
    assert bank_visible_for_request(doc_bank, requested) is expected


# ── ① 覆盖度：已知 documents.bank 取值不得漏配 ──────────────────────
@pytest.mark.parametrize("db_bank", OBSERVED_DB_BANK_VALUES)
def test_every_observed_db_bank_value_is_mappable(db_bank):
    """每个存量 documents.bank 取值要么是业务键本身，要么在 legacy 映射表内。

    否则请求对应 bank 时该文档会被静默丢弃（同类复发路径）。
    """
    covered = (db_bank in BIZKEYS) or (db_bank in LEGACY_BANK_TO_BIZKEY)
    assert covered, f"documents.bank={db_bank!r} 既非业务键也不在映射表内 ⇒ 会被静默丢弃"


# ── ② 单源一致：query_engine 映射不得与 retrieval 口径漂移 ──────────
@pytest.mark.parametrize("legacy,bizkey", sorted(LEGACY_BANK_TO_BIZKEY.items()))
def test_map_target_within_business_key_scope(legacy, bizkey):
    """映射目标必须落在该业务键的检索范围内（与 retrieval.LEGACY_BANK_TO_HS 对齐）。

    仅对 retrieval 已登记的 legacy 值校验（management/consulting 等 query_engine 专有
    别名不在 retrieval 表内，跳过）；若二者的 hs 归属出现漂移，此断言变红。
    """
    hs = retrieval.LEGACY_BANK_TO_HS.get(legacy)
    if hs is None:
        pytest.skip(f"{legacy!r} 不在 retrieval.LEGACY_BANK_TO_HS（query_engine 专有别名）")
    assert bizkey in BIZKEYS, f"映射目标 {bizkey!r} 不是合法业务键"
    assert hs in _targets_of(bizkey), (
        f"{legacy!r}→hs={hs!r} 不在业务键 {bizkey!r} 的范围 {_targets_of(bizkey)} 内 ⇒ 两表漂移")


class TestLiveDatabaseCoverage:
    """真实库覆盖度（缺库时 skip）：distinct documents.bank 值必须可映射。"""

    DB_PATH = "/home/ubuntu/kb-web/data/kb.db"

    def test_distinct_db_bank_values_are_mappable(self):
        import sqlite3
        if not os.path.exists(self.DB_PATH):
            pytest.skip(f"真实库不存在：{self.DB_PATH}")
        con = sqlite3.connect(self.DB_PATH)
        try:
            rows = con.execute(
                "SELECT DISTINCT bank FROM documents WHERE bank IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
        # 允许出现未知新值 → 若出现即告警（本用例仅断言"已登记口径"覆盖已知集合，
        # 新值提示需更新映射表，故用 fail 而非 xfail，强制人工处置）。
        unknown = [r[0] for r in rows
                   if r[0] != "skip" and r[0] not in BIZKEYS
                   and r[0] not in LEGACY_BANK_TO_BIZKEY]
        assert not unknown, (
            f"真实库出现未登记 documents.bank 取值 {unknown} ⇒ 请求对应 bank 会静默丢文档；"
            f"请补 LEGACY_BANK_TO_BIZKEY")

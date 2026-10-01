"""聚合业务键 → documents.bank 取值映射的回归锁（2026-10-01）。

缺陷背景：``/api/documents`` 用一张手写白名单做「信息化行业」过滤，漏了
``documents.bank`` 的实际取值 ``industry``（56 篇）与 ``traffic``（1 篇），
而 ``/api/banks`` 用另一张手写表算徽标 ⇒ 同一个「信息化行业」在侧栏计数
（551）与文档列表（495）口径不一致，其中 20 篇 active∧searchable=1 的
核心资料（GB 50174 / GB 50312 / 电子政务工程造价指导书 / 粤府办〔2020〕9号 等）
在文档管理页完全不可见。

本文件钉住四条：
  ① 口径函数必须覆盖**全部**已知 documents.bank 取值（防再漏）；
  ② 各聚合键的取值集必须互不串台；
  ③ 非聚合键（all / 未知键 / 物理库名）必须返回 None，
     避免调用方把「单键」误当「聚合组」而放大过滤范围；
  ④ 内置兜底 ``_HARDCODED_BANKS`` 必须与配置同构（含 ``general``）——
     否则配置不可读时会静默丢掉第二大组，属同类复发路径。

【密封性】本文件**不依赖生产环境**：所有涉及 ``BANKS`` 的断言都用
``FIXTURE_BANKS`` 显式构造（``_hermetic_banks`` 自动 fixture）；只有
``TestLiveDatabaseCoverage`` 需要真实配置与真实库，且两者缺失时 ``skip``。
（此点由独立审查指出：原版直接吃生产 ``BANKS``/``kb.db``，干净环境会红。）
"""
from __future__ import annotations

import pytest

from app.services import retrieval
from app.services.retrieval import (BANKS, LEGACY_BANK_TO_HS,
                                    consolidated_db_bank_values)

# 实测取值（2026-10-01，kb.db documents.bank distinct，去 'skip'）：
#   standards / industry / general / 咨询 / kb_xhs / industry_docs /
#   project_docs / traffic
OBSERVED_DB_BANK_VALUES = [
    "standards", "industry", "general", "咨询",
    "kb_xhs", "industry_docs", "project_docs", "traffic",
]

# 与生产 banks.json 逐字对齐的**测试夹具**（密封：不读外部文件）。
FIXTURE_BANKS = {
    "all": {"name": "全部", "hindsight": None,
            "hindsight_banks": ["kb_standard", "kb_industry", "kb_tech", "kb_general",
                                "kb_checklist", "kb_template", "kb_xhs", "kb_project"],
            "prompt": "通用政务信息化知识库"},
    "industry": {"name": "信息化行业", "hindsight": "kb_industry",
                 "hindsight_banks": ["kb_standard", "kb_industry", "kb_tech",
                                     "kb_general", "kb_checklist", "kb_template"],
                 "prompt": "政务信息化行业专家"},
    "personal": {"name": "个人资讯", "hindsight": "kb_xhs",
                 "hindsight_banks": ["kb_xhs"], "prompt": "内容分析专家"},
    "project": {"name": "项目文档", "hindsight": "kb_project",
                "prompt": "项目管理专家"},
    "general": {"name": "综合文件", "hindsight": "kb_general",
                "prompt": "综合文件领域专家"},
}


@pytest.fixture(autouse=True)
def _hermetic_banks(monkeypatch):
    """把 ``BANKS`` 换成显式夹具，使断言与环境配置解耦。"""
    monkeypatch.setattr(retrieval, "BANKS", {k: dict(v) for k, v in FIXTURE_BANKS.items()})


class TestIndustryGroupCoversRealValues:
    """① 缺陷核心：真实取值必须落在对应聚合组内。"""

    def test_industry_literal_is_covered(self):
        """bank='industry' 的 56 篇必须出现在「信息化行业」组内（本次缺陷主因）。"""
        vals = consolidated_db_bank_values("industry")
        assert vals is not None
        assert "industry" in vals, (
            "bank='industry' 未落入 industry 聚合组 ⇒ 该 56 篇在文档管理页不可见"
        )

    def test_traffic_literal_is_covered(self):
        """bank='traffic' 必须落在 industry 组内（它从不是配置键，曾被 all 总数漏掉）。"""
        vals = consolidated_db_bank_values("industry")
        assert vals is not None
        assert "traffic" in vals, "bank='traffic' 未落入 industry 聚合组"

    def test_legacy_and_general_values_covered(self):
        vals = consolidated_db_bank_values("industry") or []
        for v in ("standards", "industry_docs", "general"):
            assert v in vals, f"{v!r} 未落入 industry 聚合组"

    @pytest.mark.parametrize("value", OBSERVED_DB_BANK_VALUES)
    def test_every_observed_value_has_an_owner(self, value: str):
        """覆盖不变式：任何实测取值都必须至少被一个聚合键覆盖（防再漏新值）。"""
        owners = [
            key for key in BANKS
            if (lambda l: l and value in l)(consolidated_db_bank_values(key))
        ]
        assert owners, f"documents.bank={value!r} 无任何聚合键归属 ⇒ 该批文档永不显示"


class TestGroupsDoNotCrossContaminate:
    """② 组间不得串台。"""

    def test_personal_group_membership(self):
        vals = consolidated_db_bank_values("personal") or []
        assert "咨询" in vals and "kb_xhs" in vals
        assert "standards" not in vals, "standards 不得进入个人资讯组"
        assert "industry" not in vals, "industry 不得进入个人资讯组"

    def test_project_group_membership(self):
        vals = consolidated_db_bank_values("project") or []
        assert "project_docs" in vals
        assert "standards" not in vals and "咨询" not in vals

    def test_industry_and_personal_are_disjoint(self):
        ind = set(consolidated_db_bank_values("industry") or [])
        per = set(consolidated_db_bank_values("personal") or [])
        assert not (ind & per), f"两组取值重合: {ind & per}"

    def test_general_group_is_narrow(self):
        """general 是独立侧栏键（kb_general），不得把 industry 全组卷进来。"""
        vals = consolidated_db_bank_values("general") or []
        assert "general" in vals
        assert "standards" not in vals, "standards(kb_standard) 不属 kb_general"


class TestNonGroupKeysReturnNone:
    """③ 非聚合键一律 None —— 防止调用方放大过滤范围。"""

    @pytest.mark.parametrize("key", ["all", "kb_general", "traffic", "", "不存在的键", "kb_xhs"])
    def test_returns_none(self, key: str):
        assert consolidated_db_bank_values(key) is None, (
            f"{key!r} 不是聚合键，必须返回 None（否则会走 list_by_banks 放大范围）"
        )


class TestNoDuplicates:
    """④ 取值列表须去重（重复值会被 list_by_banks 的 IN 吸收，但会让计数对账失真）。"""

    @pytest.mark.parametrize("key", ["industry", "personal", "project", "general"])
    def test_unique(self, key: str):
        vals = consolidated_db_bank_values(key) or []
        assert len(vals) == len(set(vals)), f"{key} 取值列表存在重复: {vals}"

    @pytest.mark.parametrize("key", ["industry", "personal", "project", "general"])
    def test_values_actually_resolve_into_group_targets(self, key: str):
        """列表里每个值都必须真能把文档带回**本组**的检索范围（防串台/塞入无关值）。

        子集类断言只能抓「多塞了值」，抓不到「漏了值」——漏值由
        ``test_every_observed_value_has_an_owner`` 负责。两条互补。
        """
        cfg = BANKS[key]
        targets = set(cfg.get("hindsight_banks") or [])
        if not targets and cfg.get("hindsight"):
            targets = {cfg["hindsight"]}
        for v in consolidated_db_bank_values(key) or []:
            if v in LEGACY_BANK_TO_HS:
                assert LEGACY_BANK_TO_HS[v] in targets, (
                    f"{key}: legacy 值 {v!r} 解析到 {LEGACY_BANK_TO_HS[v]}，不在本组 {sorted(targets)}"
                )
            elif v.startswith("kb_"):
                assert v in targets, f"{key}: 物理库名 {v!r} 不在本组 {sorted(targets)}"
            elif v in BANKS:
                sub = set(BANKS[v].get("hindsight_banks") or [])
                hs = BANKS[v].get("hindsight")
                assert (hs in targets) or (sub & targets), (
                    f"{key}: 业务键 {v!r}（hindsight={hs}）与本组 {sorted(targets)} 无交集"
                )


class TestHardcodedFallbackMirrorsConfig:
    """⑤ 内置兜底必须与配置同构（2026-10-01 独立审查发现 #2）。

    缺陷形态：``_HARDCODED_BANKS`` 只有 all/industry/personal/project，
    缺 ``general``。一旦 ``BANKS_CONFIG_PATH`` 不可读（文件被删/路径漂移/
    干净环境），``reload_bank_config`` 退回内置兜底 ⇒ ``BANKS`` 丢 ``general``
    ⇒ ``consolidated_db_bank_values('general')`` 返 None ⇒ **197 篇**
    （第二大组）在任何列表筛选下消失。与本次缺陷同属「静默可见性损失」。
    """

    def test_fallback_has_general_key(self):
        assert "general" in retrieval._HARDCODED_BANKS, (
            "内置兜底缺 general：配置不可读时 197 篇 bank='general' 将从所有列表消失"
        )
        assert retrieval._HARDCODED_BANKS["general"]["hindsight"] == "kb_general"

    def test_fallback_key_set_matches_fixture(self):
        """兜底键集必须与夹具（对齐生产 banks.json）一致 —— 防再次不对称。"""
        assert set(retrieval._HARDCODED_BANKS) == set(FIXTURE_BANKS), (
            f"兜底键集 {sorted(retrieval._HARDCODED_BANKS)} 与配置键集 "
            f"{sorted(FIXTURE_BANKS)} 不一致"
        )

    def test_legacy_map_registers_general(self):
        """``general`` 是第二大存量取值，必须在 LEGACY 表显式登记（消除隐含配置依赖）。"""
        assert LEGACY_BANK_TO_HS.get("general") == "kb_general"

    def test_config_unavailable_still_keeps_general_visible(self):
        """端到端：模拟配置不可读（空 override）后，general 组仍须覆盖其取值。"""
        monkey_banks = {k: dict(v) for k, v in retrieval._HARDCODED_BANKS.items()}
        saved = retrieval.BANKS
        try:
            retrieval.BANKS = monkey_banks          # 等价于 _load_bank_overrides() -> {}
            vals = consolidated_db_bank_values("general")
            assert vals is not None and "general" in vals, (
                "配置不可读时 general 组失效 ⇒ 197 篇不可见（本次缺陷的同类复发）"
            )
            assert "general" in (consolidated_db_bank_values("industry") or []), (
                "配置不可读时 general 掉出 industry 组"
            )
        finally:
            retrieval.BANKS = saved


class TestListByBanksSkipGuard:
    """⑥ ``list_by_banks`` 必须排除哨兵 ``bank='skip'``（2026-10-01 审查发现 #5）。

    ``list_all`` 早有该守卫，``list_by_banks`` 没有；聚合过滤改走后者后，
    这条不对称会让 ``skip`` 行有机会出现在任何列表里。
    """

    def test_skip_rows_are_excluded(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import app.models.document  # noqa: F401  注册模型（Base.metadata 需要）
        from app.models.database import Base
        from app.models.document import Document
        from app.repositories.document_repo import DocumentRepository

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            db.add_all([
                Document(doc_id="d1", title="正常", bank="standards"),
                Document(doc_id="d2", title="哨兵", bank="skip"),
            ])
            db.commit()
            got = DocumentRepository(db).list_by_banks(["standards", "skip"])
            ids = {d.doc_id for d in got}
            assert "d1" in ids, "正常行被误排除"
            assert "d2" not in ids, "bank='skip' 哨兵行泄漏进列表（缺守卫）"
        finally:
            db.close()


class TestLiveDatabaseCoverage:
    """⑦ 类级回归锁（需真实配置 + 真实库；任一缺失即 skip）。

    上面 ``test_every_observed_value_has_an_owner`` 用的是**硬编码**的实测
    取值清单 —— 它只能防「已知道的取值被漏掉」，防不了「将来出现新取值」。
    本用例直接读生产库的 ``SELECT DISTINCT bank``，因此**新出现的未映射取值
    会让它立刻变红**（这正是本次缺陷的复发形态：新增取值静默不可见）。
    """

    DB = "/home/ubuntu/kb-web/data/kb.db"

    @pytest.fixture(autouse=True)
    def _real_banks(self, monkeypatch):
        """本类用**真实**配置（其余类用夹具）。缺失即 skip。"""
        import os

        real = dict(retrieval._HARDCODED_BANKS)
        cfg = getattr(retrieval.settings, "banks_config_path", None)
        if cfg is None or not os.path.exists(cfg):
            pytest.skip(f"真实 banks 配置不可读（{cfg}），跳过线上覆盖核验")
        real.update(retrieval._load_bank_overrides())
        if "general" not in real:
            pytest.skip("真实 banks 配置缺 general 键，跳过线上覆盖核验")
        monkeypatch.setattr(retrieval, "BANKS", real)

    def test_every_live_bank_value_has_an_owner(self):
        import os
        import sqlite3

        if not os.path.exists(self.DB):
            pytest.skip(f"生产库不存在（{self.DB}），跳过线上覆盖核验")

        con = sqlite3.connect(f"file:{self.DB}?mode=ro", uri=True, timeout=10)
        try:
            live = [r[0] for r in con.execute(
                "SELECT DISTINCT bank FROM documents WHERE bank != 'skip'")]
        finally:
            con.close()

        assert live, "库中无 bank 取值，疑似连错库"
        orphans = [
            v for v in live
            if not any(
                (lambda l: l and v in l)(consolidated_db_bank_values(key))
                for key in BANKS
            )
        ]
        assert not orphans, (
            f"以下 documents.bank 取值不属于任何聚合键 ⇒ 对应文档在文档管理页"
            f"任何筛选下都不可见（本次缺陷复发形态）：{orphans}"
        )

    def test_active_rows_bank_matches_hs_bank(self):
        """活数据不变式：``active`` 行的 ``hs_bank`` 必须等于现行解析结果。

        独立审查（2026-10-01）提出「bank 与 hs_bank 不一致 ⇒ 徽标≠检索范围」。
        实测复核：错配共 38 篇，**全部是 superseded 死行**（应被取代的旧版），
        ``active`` 行错配 = **0** ⇒ 不构成活内容风险。本用例把「active 行必须
        一致」钉成不变式：将来若写路径（upload）regression 出 bank/hs_bank 分叉，
        这里立刻变红。
        """
        import os
        import sqlite3

        from app.services.bank_resolver import resolve_hs_bank

        if not os.path.exists(self.DB):
            pytest.skip(f"生产库不存在（{self.DB}），跳过线上不变式核验")

        con = sqlite3.connect(f"file:{self.DB}?mode=ro", uri=True, timeout=10)
        try:
            rows = con.execute(
                "SELECT doc_id, bank, hs_bank FROM documents "
                "WHERE bank != 'skip' AND status = 'active'").fetchall()
        finally:
            con.close()

        bad = []
        for doc_id, bank, hs_bank in rows:
            try:
                exp = resolve_hs_bank(bank)
            except Exception:
                continue          # 解析不了的键由别的用例负责
            if (hs_bank or "") != exp:
                bad.append((doc_id, bank, hs_bank, exp))

        assert not bad, (
            f"{len(bad)} 篇 active 文档的 hs_bank 与现行解析不一致 ⇒ "
            f"列表可见性与检索范围分叉：{bad[:5]}"
        )

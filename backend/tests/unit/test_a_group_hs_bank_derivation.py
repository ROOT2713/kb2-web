"""A 组参数化派生测试 — F1（测试先行）

═══════════════════════════════════════════════════════════════════
本文件是 F2（``resolve_hs_bank()`` 共享函数 + 白名单 + 422 + fail-fast）
的「红灯基线」。**F1 阶段预期全部 FAIL** —— 失败本身就是缺陷已复现的证据，
不是测试写错。

已实证的 A 组缺陷（2026-09-28 审计）：
  1) ``PATCH /api/documents/{doc_id}/bank``（documents.py:1017-1032）
     只写 ``doc.bank``，**不写 ``doc.hs_bank``**
     → SQL 路过滤走 ``documents.hs_bank``（retrieval.py:103），
       向量路过滤走 ``vector_chunks.bank``（vector_repo.py:366），
       改 bank 后两路口径不一致，文档仍留在旧库的检索结果里。
  2) 派生表达式 ``bank_cfg["hindsight"] or "kb"``（documents.py:281、1227）
     → 对 ``all``（hindsight=None）、legacy 业务键（standards/industry_docs/咨询…）、
       未知键 一律落 ``"kb"`` 黑洞。实测推演：
       ``get_bank_config(k)["hindsight"] or "kb"`` 对
       all / standards / 行业 / 未知键 / kb_xhs **全部**落到 "kb"。
  3) 无单一解析入口：读路径有 ``LEGACY_BANK_TO_HS``（retrieval.py:53），
     写路径 ``reparse``（documents.py:1225-1227）却不走它。

F2 落地后本文件应全绿；F2 的验收标准就是本文件 0 failed。
═══════════════════════════════════════════════════════════════════
"""

import re
from pathlib import Path

import pytest

from app.models.document import Document
from app.services.retrieval import BANKS, LEGACY_BANK_TO_HS

DOCUMENTS_PY = Path(__file__).resolve().parents[2] / "app" / "api" / "documents.py"

# 4 个具体业务键 → 应派生的物理库（不含聚合键 all）
BUSINESS_KEY_TO_HS = {
    "industry": "kb_industry",
    "personal": "kb_xhs",
    "project": "kb_project",
    "general": "kb_general",
}


def _mk_doc(db_session, doc_id, bank="general", hs_bank="kb_general"):
    """建测试文档。默认起点用 legacy 键，确保「切换到目标 bank」必然产生可观测变化，
    避免起点恰好等于目标导致断言假绿。"""
    doc = Document(
        doc_id=doc_id,
        title=f"测试文档 {doc_id}",
        bank=bank,
        hs_bank=hs_bank,
        status="active",
        searchable=1,
    )
    db_session.add(doc)
    db_session.commit()
    return doc


# 起点：legacy 键（不在 BANKS 中，也不等于任何目标键）→ 切到任何目标都必须真变化
START_BANK = "standards"
START_HS = "kb_standard"


# ═══════════════════════════════════════════════════════════════════
# A1. PATCH /{doc_id}/bank 必须同步 hs_bank（参数化 4 个业务键）
#     当前实现只写 doc.bank → 本组全部 FAIL（预期）
# ═══════════════════════════════════════════════════════════════════

class TestA1PatchBankSyncsHsBank:

    @pytest.mark.parametrize(
        "bank_key,expected_hs",
        sorted(BUSINESS_KEY_TO_HS.items()),
        ids=sorted(BUSINESS_KEY_TO_HS.keys()),
    )
    def test_patch_writes_both_bank_and_hs_bank(self, client, db_session, bank_key, expected_hs):
        """改 bank 后 documents.hs_bank 必须同步为该 bank 对应的物理库。

        只写 doc.bank = 半套生效：SQL 路（hs_bank 过滤）仍命中旧库。
        起点用 legacy 对（standards/kb_standard），确保切到任何目标都须真变化。
        """
        _mk_doc(db_session, f"doc-a1-{bank_key}", bank=START_BANK, hs_bank=START_HS)

        resp = client.patch(f"/api/documents/doc-a1-{bank_key}/bank", data={"bank": bank_key})
        assert resp.status_code == 200, f"PATCH 失败: {resp.status_code} {resp.text[:200]}"

        db_session.expire_all()
        got = db_session.query(Document).filter_by(doc_id=f"doc-a1-{bank_key}").one()
        assert got.bank == bank_key, f"doc.bank 应为 {bank_key}，实际 {got.bank!r}"
        assert got.hs_bank == expected_hs, (
            f"doc.hs_bank 未同步：期望 {expected_hs!r}，实际 {got.hs_bank!r}。"
            f"（PATCH 只写了 doc.bank —— A 组缺陷 1）"
        )

    @pytest.mark.parametrize(
        "bank_key,expected_hs",
        sorted(BUSINESS_KEY_TO_HS.items()),
        ids=sorted(BUSINESS_KEY_TO_HS.keys()),
    )
    def test_hs_bank_never_blackhole_after_patch(self, client, db_session, bank_key, expected_hs):
        """起点已是 'kb' 黑洞时，PATCH 必须把它修正为目标物理库。

        （起点置 'kb' 使断言有牙齿：若 PATCH 不同步 hs_bank，则它一直留在 'kb'。）
        """
        _mk_doc(db_session, f"doc-a1b-{bank_key}", bank="standards", hs_bank="kb")
        client.patch(f"/api/documents/doc-a1b-{bank_key}/bank", data={"bank": bank_key})

        db_session.expire_all()
        got = db_session.query(Document).filter_by(doc_id=f"doc-a1b-{bank_key}").one()
        assert got.hs_bank != "kb", "'kb' 是黑洞/读侧全库哨兵，写路径派生绝不允落到它"
        assert got.hs_bank == expected_hs, (
            f"黑洞未被修正：期望 {expected_hs!r}，实际 {got.hs_bank!r}"
        )

    def test_patch_is_not_silently_stale(self, client, db_session):
        """反例锁：hs_bank 不得在 PATCH 后静默保持旧值（跨库切换场景）。"""
        _mk_doc(db_session, "doc-a1c", bank="general", hs_bank="kb_general")

        resp = client.patch("/api/documents/doc-a1c/bank", data={"bank": "personal"})
        assert resp.status_code == 200

        db_session.expire_all()
        got = db_session.query(Document).filter_by(doc_id="doc-a1c").one()
        assert got.hs_bank != "kb_general", (
            "从 general 切到 personal 后 hs_bank 仍为 kb_general = 静默失同步（缺陷 1）"
        )


# ═══════════════════════════════════════════════════════════════════
# A2. 聚合键 'all' 不得静默失同步 / 不得落黑洞
# ═══════════════════════════════════════════════════════════════════

class TestA2AggregateBankNotSilentlyStale:

    def test_all_bank_must_not_leave_hs_bank_unchanged(self, client, db_session):
        """bank='all' 是聚合键（hindsight=None，覆盖 8 库），写 hs_bank 无单一意义。

        要求：要么明确拒绝（4xx，fail-fast），要么给出确定的合法物理库；
        绝不允许「200 + hs_bank 静默不变」这种假成功。
        """
        _mk_doc(db_session, "doc-a2", bank="general", hs_bank="kb_general")

        resp = client.patch("/api/documents/doc-a2/bank", data={"bank": "all"})

        db_session.expire_all()
        got = db_session.query(Document).filter_by(doc_id="doc-a2").one()

        if resp.status_code == 200:
            assert got.hs_bank != "kb_general", (
                "bank='all' 返回 200 但 hs_bank 静默不变 = 假成功；"
                "应 fail-fast(4xx) 或显式写入合法物理库"
            )
            assert got.hs_bank != "kb", "bank='all' 派生落 'kb' 黑洞（缺陷 2）"
        else:
            assert 400 <= resp.status_code < 500, (
                f"拒绝方式应为 4xx 客户端错误，实际 {resp.status_code}"
            )


# ═══════════════════════════════════════════════════════════════════
# A3. 共享解析入口契约 —— app.services.bank_resolver.resolve_hs_bank
#     F2 交付物。当前模块不存在 → ImportError = 红灯（预期）
# ═══════════════════════════════════════════════════════════════════

def _resolve_hs_bank(key):
    """F2 预期提供的唯一解析入口；不存在则本测试红。"""
    from app.services.bank_resolver import resolve_hs_bank  # noqa: F2 落地
    return resolve_hs_bank(key)


class TestA3SharedResolverContract:

    @pytest.mark.parametrize(
        "bank_key,expected_hs",
        sorted(BUSINESS_KEY_TO_HS.items()),
        ids=sorted(BUSINESS_KEY_TO_HS.keys()),
    )
    def test_resolves_business_key(self, bank_key, expected_hs):
        """业务键 → 对应物理库。"""
        assert _resolve_hs_bank(bank_key) == expected_hs

    @pytest.mark.parametrize(
        "legacy_key,expected_hs",
        sorted(LEGACY_BANK_TO_HS.items()),
        ids=[k for k, _ in sorted(LEGACY_BANK_TO_HS.items())],
    )
    def test_resolves_legacy_key(self, legacy_key, expected_hs):
        """legacy 业务键必须走 LEGACY_BANK_TO_HS 映射，不得落 'kb'（缺陷 3）。

        这些键实际存在于存量 documents.bank（standards/industry_docs/咨询 等）。
        """
        got = _resolve_hs_bank(legacy_key)
        assert got == expected_hs, f"legacy 键 {legacy_key!r} 应映射到 {expected_hs!r}，实际 {got!r}"
        assert got != "kb", f"legacy 键 {legacy_key!r} 派生落 'kb' 黑洞（缺陷 2）"

    @pytest.mark.parametrize("kb_name", sorted({v for v in LEGACY_BANK_TO_HS.values()}))
    def test_passthrough_already_physical_name(self, kb_name):
        """已是物理库名（kb_*）时原样透传，不得再被解析成 'kb'。"""
        assert _resolve_hs_bank(kb_name) == kb_name

    def test_every_banks_key_resolves_to_real_bank(self):
        """BANKS 中每个具体键派生结果必须是真实物理库（all 除外）。"""
        for key in BANKS:
            if key == "all":
                continue
            got = _resolve_hs_bank(key)
            assert got != "kb", f"BANKS[{key!r}] 派生落 'kb' 黑洞"
            assert got.startswith("kb_"), f"BANKS[{key!r}] 派生 {got!r} 不是物理库名"


# ═══════════════════════════════════════════════════════════════════
# A4. 未知键必须 fail-fast，不得静默兜底
# ═══════════════════════════════════════════════════════════════════

class TestA4ResolverFailFast:

    @pytest.mark.parametrize(
        "bad_key",
        ["", "  ", "no_such_bank", "kb_", "all"],
        ids=["empty", "blank", "unknown", "partial_prefix", "aggregate"],
    )
    def test_unknown_key_raises_not_blackhole(self, bad_key):
        """真正非法/未知的键必须抛错（fail-fast），绝不能静默返回 'kb'。

        静默兜底 = 内容写进谁都不查的库，且调用方看不到任何异常。
        注：大小写/空白变体不列入本表（可能是可规范化的合法真值，见下方独立用例），
        避免「期望写错」造成的假红。
        """
        from app.services.bank_resolver import resolve_hs_bank

        try:
            got = resolve_hs_bank(bad_key)
        except Exception:
            return  # ✅ fail-fast，符合要求
        pytest.fail(f"resolve_hs_bank({bad_key!r}) 未报错，返回 {got!r}（应 fail-fast）")

    @pytest.mark.parametrize(
        "variant,expected_hs",
        [("KB_INDUSTRY", "kb_industry"), ("industry ", "kb_industry"),
         (" Industry", "kb_industry"), ("PERSONAL", "kb_xhs")],
        ids=["upper", "trailing_space", "leading_space", "upper_personal"],
    )
    def test_case_whitespace_variant_not_silent_blackhole(self, variant, expected_hs):
        """大小写/空白变体：要么规范化到正确物理库，要么抛错。

        本用例不断言「必须拒绝」（那属期望写错），只断言**不得静默落 'kb'** ——
        这才是缺陷 2 的真实边界。
        """
        from app.services.bank_resolver import resolve_hs_bank

        try:
            got = resolve_hs_bank(variant)
        except Exception:
            return  # ✅ 拒绝也是可接受行为
        assert got != "kb", f"{variant!r} 静默落 'kb' 黑洞（缺陷 2）"
        assert got == expected_hs, (
            f"{variant!r} 被接受但解析为 {got!r}，期望 {expected_hs!r}"
            f"（若有意不做规范化，应改为抛错）"
        )


# ═══════════════════════════════════════════════════════════════════
# A5. 防回退锁：写路径不得再用 `hindsight ... or "kb"` 兜底
#     读侧 'kb' 是全库哨兵（合法），故只锁「派生后赋值给 hs_bank」的那些行。
# ═══════════════════════════════════════════════════════════════════

class TestA5NoBlackholeFallbackInDerivation:

    BLACKHOLE_FALLBACK = re.compile(
        r"""hs_bank\s*=\s*[^\n]*hindsight[^\n]*?\bor\s*["']kb["']"""
    )

    def test_documents_py_has_no_hindsight_or_kb_fallback(self):
        """documents.py 中不得存在 `hs_bank = ... hindsight ... or "kb"` 形态。

        实测现存 2 处（documents.py:281、1227）→ 本测试当前 RED。
        F2 应改为调用 resolve_hs_bank()，由它统一 fail-fast。
        """
        src = DOCUMENTS_PY.read_text(encoding="utf-8")
        hits = [
            (i + 1, line.strip())
            for i, line in enumerate(src.splitlines())
            if self.BLACKHOLE_FALLBACK.search(line)
        ]
        assert not hits, (
            "documents.py 仍存在 hs_bank 派生的裸 'kb' 兜底：\n"
            + "\n".join(f"  L{n}: {t}" for n, t in hits)
        )


# ═══════════════════════════════════════════════════════════════════
# A6. 第 8 处口径：DocumentRepository.save() 的双默认值
#     document_repo.py:43-44 → ``bank="general", hs_bank="kb_general"``
#     调用方漏传 hs_bank 时静默写入 kb_general（**在 industry 检索范围内**）；
#     且 bank 与 hs_bank 无一致性校验，可写入自相矛盾的物理归属。
#     当前实现 → 本组全部 FAIL（预期）
# ═══════════════════════════════════════════════════════════════════

class TestA6SaveDefaultsFailFast:

    def test_save_without_hs_bank_must_not_silently_default(self, db_session):
        """save() 不显式传 hs_bank 时，不得静默兜底成 kb_general。

        要求：hs_bank 变为必传（缺失即抛错），或由 bank 经 resolve_hs_bank 派生。
        当前实现有默认值 ``hs_bank="kb_general"``（document_repo.py:44）→ 静默落库 → RED。

        先做健全性前置：证明 save() 在参数齐全时确实可用 ——
        否则「抛异常」可能来自无关原因，造成假绿。
        """
        from app.repositories.document_repo import DocumentRepository

        repo = DocumentRepository(db_session)

        # ── 健全性前置：参数齐全时必须成功（排除无关异常导致的假绿）──
        repo.save(doc_id="a6-sanity", title="A6 健全性", bank="general", hs_bank="kb_general")
        assert repo.get("a6-sanity") is not None, "save() 在参数齐全时都失败 → 本测试基线无效"

        # ── 被测行为 ──
        try:
            repo.save(doc_id="a6-no-hs", title="A6 未传 hs_bank")
        except Exception:
            return  # ✅ fail-fast，符合要求
        doc = repo.get("a6-no-hs")
        pytest.fail(
            f"save() 未传 hs_bank 仍成功落库（hs_bank={doc.hs_bank!r}）—— "
            f"document_repo.py:44 的双默认值静默生效"
        )

    def test_save_mismatched_bank_and_hs_bank_must_raise(self, db_session):
        """save() 显式传值时，bank 与 hs_bank 必须经 resolve_hs_bank 校验一致。

        ``bank='personal'``（小红书隔离库）却传 ``hs_bank='kb_general'``
        属自相矛盾的物理归属 → 必须抛错，不得静默写入。
        """
        from app.repositories.document_repo import DocumentRepository

        repo = DocumentRepository(db_session)
        try:
            repo.save(
                doc_id="a6-mismatch",
                title="A6 bank/hs_bank 矛盾",
                bank="personal",
                hs_bank="kb_general",
            )
        except Exception:
            return  # ✅ 校验生效，符合要求
        doc = repo.get("a6-mismatch")
        pytest.fail(
            f"save(bank='personal', hs_bank='kb_general') 未报错，静默写入 "
            f"(bank={doc.bank!r}, hs_bank={doc.hs_bank!r}) —— 缺 resolve_hs_bank 一致性校验"
        )

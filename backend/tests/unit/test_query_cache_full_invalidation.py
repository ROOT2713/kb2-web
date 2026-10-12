"""方案A 回归锁：`invalidate_query_cache_by_bank` 必须**整表清空**（2026-10-12）。

背景（真实缺口，只读 SQL 实测）：上传落到物理库 ``kb_standard`` 时其业务键是
``standards``，旧实现只清 ``bank IN ('standards','all')`` → 实测「清 1 行、存活 4 行」；
而聚合库 ``industry`` 的检索范围（vector_banks）**包含** ``kb_standard`` ⇒
用 industry 问过的问题在 standards 重入库后仍命中旧答案。

本文件三条断言各司其职：
① 新口径：任意 bank 触发 → 整表清空（跨库行不得存活）；
② 反向核验：换回旧口径 → 跨库行**必须存活**（证明 ① 的断言有牙齿、缺陷可复现）；
③ 冒烟：函数可调用不抛错。

夹具写入后由被测函数自身清空 ⇒ 用例天然自清理，不污染后续用例。
"""

from sqlalchemy import text

from app.models.database import SessionLocal
from app.services.cache_service import invalidate_query_cache_by_bank


def _seed(banks):
    """用与生产同一个 SessionLocal 写夹具（commit 后对被测函数可见）。

    注意 ``created_at`` 是 NOT NULL 且**无 DB 级默认值**（SQLAlchemy 层 default），
    裸 SQL 插入必须显式给值，否则 IntegrityError。
    """
    db = SessionLocal()
    try:
        for i, bank in enumerate(banks):
            db.execute(
                text(
                    "INSERT INTO query_cache "
                    "(cache_id, query_text, bank, answer, scope, created_at) "
                    "VALUES (:cid, :q, :b, :a, :s, :ts)"
                ),
                {
                    "cid": f"probe-{i}-{bank}",
                    "q": f"q{i}",
                    "b": bank,
                    "a": "old-answer-based-on-stale-docs",
                    "s": "",
                    "ts": "2026-10-12 00:00:00",
                },
            )
        db.commit()
    finally:
        db.close()


def _banks_in_cache():
    db = SessionLocal()
    try:
        return [r[0] for r in db.execute(text("SELECT bank FROM query_cache")).fetchall()]
    finally:
        db.close()


def _wipe():
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM query_cache"))
        db.commit()
    finally:
        db.close()


def test_invalidate_by_bank_clears_whole_table():
    """① 核心断言：上传到任一小库，整表都必须清空（旧口径会漏掉聚合库）。"""
    _seed(["standards", "industry", "general"])
    assert len(_banks_in_cache()) >= 3  # 夹具前置：确认真的写进去了

    invalidate_query_cache_by_bank("standards")  # 模拟上传落到 kb_standard

    leftover = _banks_in_cache()
    assert leftover == [], (
        f"整表清空要求无残留，实得 {leftover}；"
        "残留 industry/general = 聚合库漏清缺陷回归（旧口径只清 standards+all）"
    )


def test_mutation_bank_scoped_delete_leaves_other_banks(monkeypatch):
    """② 反向核验：把实现换回旧的 bank 精确清 → 跨库行必须存活。

    若本用例变红（= 旧口径也把整表清了），说明 ① 的断言没有区分力。
    """
    import app.services.cache_service as cs

    def _old_scope(bank: str) -> None:
        db = cs.SessionLocal()
        try:
            db.execute(
                text("DELETE FROM query_cache WHERE bank IN (:b1, :b2)"),
                {"b1": bank, "b2": "all"},
            )
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr(cs, "invalidate_query_cache_by_bank", _old_scope)
    try:
        _seed(["standards", "industry", "general"])
        cs.invalidate_query_cache_by_bank("standards")
        leftover = set(_banks_in_cache())
        assert leftover == {"industry", "general"}, (
            f"旧口径应漏清跨库行，实得残留 {leftover}"
        )
    finally:
        _wipe()  # 自清理，避免污染后续用例


def test_invalidate_by_bank_when_table_empty_does_not_raise():
    """③ 冒烟：空表上调用不得抛错。"""
    _wipe()
    invalidate_query_cache_by_bank("industry")

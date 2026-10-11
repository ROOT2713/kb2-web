"""B-1 回归锁：'all' 逻辑 bank 必须覆盖全部物理向量库（含 kb_standard）。

背景：M2 根因 = pgvector 主路径复用 Hindsight 时代的 _get_active_hindsight_banks，
只读单值键 hindsight，丢掉 vector_banks 清单 ⇒ kb_standard 静默漏检。
本锁钉住：(1) 清单键存在且被 _get_active_banks 消费；(2) kb_standard 在内。
"""
import asyncio

from app.services import retrieval


def test_all_bank_has_vector_banks_constant():
    assert "vector_banks" in retrieval.BANKS["all"]
    assert retrieval.BANKS["all"]["vector_banks"] == retrieval.ALL_VECTOR_BANKS
    assert "kb_standard" in retrieval.ALL_VECTOR_BANKS


def test_get_active_banks_covers_standard(monkeypatch):
    monkeypatch.setattr(retrieval.settings, "vector_backend", "pgvector")
    act = asyncio.run(retrieval._get_active_banks())
    assert "kb_standard" in act, f"kb_standard 漏检: {act}"
    assert set(act) >= {"kb_standard", "kb_industry", "kb_xhs", "kb_project", "kb_general"}


def test_get_active_banks_reads_list_key_not_only_scalar(monkeypatch):
    """突变守护：删掉 vector_banks 的消费分支应使本断言失败。"""
    monkeypatch.setattr(retrieval.settings, "vector_backend", "pgvector")
    monkeypatch.setitem(retrieval.BANKS, "all", dict(retrieval.BANKS["all"]))
    retrieval.BANKS["all"]["vector_banks"] = ["kb_standard", "kb_marker_bank"]
    act = asyncio.run(retrieval._get_active_banks())
    assert "kb_marker_bank" in act, "vector_banks 清单未被消费（退化回只读单值键）"

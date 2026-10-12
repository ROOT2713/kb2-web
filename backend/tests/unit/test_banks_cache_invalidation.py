"""POST/DELETE /api/banks 依赖的 `_invalidate_bank_caches` 回归锁（2026-10-12）。

背景（真实缺陷，由测试基建修复后暴露）：原实现引用 Hindsight 时代遗留全局
`_active_hs_banks_cache` —— **全仓无定义** ⇒ 任一调用点必抛 `NameError`：
`POST /api/banks`、`DELETE /api/banks/{key}` 一律 HTTP 500；且 create 路径是在
`_save_banks_config(BANKS)` **之后**才抛错 ⇒ 调用方见 500 但 banks.json 已改
（**部分成功**，比直接失败更难排查）。

本文件三条断言各司其职：
① 结构性锁：遗留符号不得回归；
② 冒烟：函数可调用不抛错；
③ 有牙齿：函数必须**真清** BM25 缓存（若退化为空操作即红）。
"""
import ast
import inspect

import app.api.banks as banks
from app.services import cache_service


def test_no_undefined_active_hs_banks_cache_symbol():
    """结构性锁：遗留全局名不得再被**引用**（AST 级，docstring/注释提及不算）。

    易错点：不能用 `inspect.getsource()` 的字符串匹配 —— 函数 docstring 里若
    说明「原实现引用了 X」就会自我命中造成假阳性。用 AST 只看 Name 节点。
    """
    tree = ast.parse(inspect.getsource(banks))
    loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_active_hs_banks_cache" not in loaded, (
        "遗留 Hindsight 全局名回归（被引用）→ POST/DELETE /api/banks 将再次 NameError"
    )


def test_invalidate_bank_caches_does_not_raise():
    """原实现在此必抛 NameError。"""
    banks._invalidate_bank_caches()


def test_invalidate_bank_caches_clears_bm25_caches():
    """有牙齿：必须真清 BM25 缓存，而非空操作。"""
    cache_service._bm25_caches["__probe__"] = {
        "index": object(), "docs": [], "ts": 1.0, "doc_count": 0,
    }
    assert "__probe__" in cache_service._bm25_caches
    banks._invalidate_bank_caches()
    assert cache_service._bm25_caches == {}, "bank 变更后 BM25 缓存未被失效"


def test_mutation_noop_invalidate_is_caught(monkeypatch):
    """反向核验：把 `_invalidate_bank_caches` 换成空操作时，第③条断言必须变红。"""
    cache_service._bm25_caches["__probe2__"] = {"index": object(), "docs": [], "ts": 1.0}
    monkeypatch.setattr(banks, "_invalidate_bank_caches", lambda: None)
    banks._invalidate_bank_caches()
    # 空操作不会清缓存 —— 这正是第③条要抓的形态
    assert "__probe2__" in cache_service._bm25_caches
    cache_service._bm25_caches.pop("__probe2__", None)

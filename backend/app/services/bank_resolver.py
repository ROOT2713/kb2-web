"""bank 解析唯一入口 —— 业务键/legacy 键 → 物理库名（hindsight bank）。

┌─ 为什么需要它 ────────────────────────────────────────────────────┐
│ A 组审计（2026-09-28）确认写路径存在 9 处各自的派生实现，形态不一，  │
│ 且普遍带 ``... or "kb"`` 兜底。而 "kb" 是**读侧的全库哨兵**：       │
│ recall() 里 ``bank in ("all", "kb") or not hs_bank`` 才走「并行查   │
│ 全部库」；把 "kb" 写进 documents.hs_bank 的后果是 —— 该文档在**任何 │
│ 定向 bank 查询中都命中不到**（黑洞），而写路径返回成功、无任何日志  │
│ 级别之上的信号。                                                  │
│                                                                  │
│ 实证：kb_general 的 active 文档数曾因「xhs 内容 + legacy 键 +      │
│ save() 双默认值」三条路径而虚高；q 侧已按 source 归位，但根因在写  │
│ 路径未收口 —— 故此处收口。                                        │
└──────────────────────────────────────────────────────────────────┘

调用方（F2 后全部改为调用本模块，不再自行派生）：
  app/api/upload.py            （主上传路径）
  app/api/documents.py         （fetch-standard / refetch / PATCH bank / reparse）
  app/repositories/document_repo.py （save() 一致性校验）

契约（由 tests/unit/test_a_group_hs_bank_derivation.py A3/A4 锁定）：
  1. 业务键（BANKS 内非聚合键）→ 其 hindsight 物理库
  2. legacy 键（LEGACY_BANK_TO_HS，含中文键）→ 映射的物理库
  3. 已是物理库名（kb_*）→ 原样透传，但必须在已知库集合内
  4. 大小写 / 首尾空白 → 先规范化再解析（不做模糊"猜"）
  5. 聚合键 ``all``、空串、纯空白、未知键 → **抛 BankResolutionError**
     —— 绝不返回 "kb"。调用方须转为 4xx，不得静默兜底。
"""
from __future__ import annotations

from app.services.retrieval import BANKS, LEGACY_BANK_TO_HS

__all__ = [
    "BankResolutionError",
    "AGGREGATE_BANK_KEYS",
    "KNOWN_HS_BANKS",
    "resolve_hs_bank",
    "validate_bank_pair",
]

# 聚合键：跨多库，没有单一物理库可写入
AGGREGATE_BANK_KEYS = frozenset({"all"})

# 已知物理库名集合：BANKS 的 hindsight 值 ∪ 各 hindsight_banks ∪ LEGACY 目标值
KNOWN_HS_BANKS = frozenset(
    {cfg["hindsight"] for cfg in BANKS.values() if cfg.get("hindsight")}
    | {b for cfg in BANKS.values() for b in (cfg.get("hindsight_banks") or [])}
    | set(LEGACY_BANK_TO_HS.values())
)


class BankResolutionError(ValueError):
    """非法 / 未知 / 聚合 bank 键。

    调用方必须转成 4xx（客户端错误），**不得** 静默兜底到 "kb"：
    静默兜底会把内容写进谁都不定向检索的库，且调用方看不到任何异常。
    """


def resolve_hs_bank(bank_key) -> str:
    """把任意 bank 键解析为唯一物理库名；无法解析即抛 BankResolutionError。

    >>> resolve_hs_bank("personal")
    'kb_xhs'
    >>> resolve_hs_bank("standards")     # legacy 键
    'kb_standard'
    >>> resolve_hs_bank("KB_INDUSTRY")   # 大小写变体
    'kb_industry'
    >>> resolve_hs_bank("kb_xhs")        # 已是物理库名 → 透传
    'kb_xhs'
    >>> resolve_hs_bank("all")
    Traceback (most recent call last):
    ...
    app.services.bank_resolver.BankResolutionError: 'all' 是聚合键...
    """
    if bank_key is None:
        raise BankResolutionError("bank 键为 None（空值）")

    raw = str(bank_key)
    key = raw.strip()
    if not key:
        raise BankResolutionError(f"bank 键为空白（原始 {raw!r}）")

    low = key.lower()

    # ── 5) 聚合键：无单一物理库 ──
    if low in AGGREGATE_BANK_KEYS:
        concrete = sorted(set(BANKS) - AGGREGATE_BANK_KEYS)
        raise BankResolutionError(
            f"{key!r} 是聚合键（跨库检索），没有单一物理库可写入；"
            f"请先确定具体业务键，合法值：{concrete}"
        )

    # ── 3) 已是物理库名 → 透传（须在已知库集合内） ──
    if low.startswith("kb_"):
        if low in KNOWN_HS_BANKS:
            return low
        raise BankResolutionError(
            f"{key!r} 形如物理库名（kb_ 前缀）但不在已知库集合内："
            f"{sorted(KNOWN_HS_BANKS)}"
        )

    # ── 1) 业务键（BANKS） ──
    cfg = BANKS.get(low)
    if cfg and cfg.get("hindsight"):
        return cfg["hindsight"]

    # ── 2) legacy 键（含中文键；原名优先，其次规范化名） ──
    for cand in (key, low):
        if cand in LEGACY_BANK_TO_HS:
            return LEGACY_BANK_TO_HS[cand]

    raise BankResolutionError(
        f"{key!r} 不是已知业务键 / legacy 键 / 物理库名；"
        f"拒绝静默兜底（业务键：{sorted(set(BANKS) - AGGREGATE_BANK_KEYS)}，"
        f"legacy 键：{sorted(LEGACY_BANK_TO_HS)}）"
    )


def validate_bank_pair(bank, hs_bank) -> str:
    """校验 (bank, hs_bank) 这对「业务键 ↔ 物理库」是否自洽，返回规范 hs_bank。

    hs_bank 为 None → 无法自洽（上层必须显式派生），抛错。
    用于 DocumentRepository.save()：阻止「bank='personal' 却写 kb_general」
    这类自相矛盾的物理归属落库。
    """
    expected = resolve_hs_bank(bank)
    if hs_bank is None:
        raise BankResolutionError(
            f"hs_bank 未提供：应显式传 resolve_hs_bank({bank!r})={expected!r}，"
            f"不得静默默认"
        )
    if str(hs_bank) != expected:
        raise BankResolutionError(
            f"bank={bank!r} 与 hs_bank={hs_bank!r} 不自洽："
            f"按 resolve_hs_bank 应为 {expected!r}"
        )
    return expected

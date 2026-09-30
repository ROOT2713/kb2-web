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

import logging

from app.services.retrieval import BANKS, LEGACY_BANK_TO_HS

logger = logging.getLogger(__name__)

__all__ = [
    "BankResolutionError",
    "AGGREGATE_BANK_KEYS",
    "KNOWN_HS_BANKS",
    "resolve_hs_bank",
    "resolve_delete_hs_bank",
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


def resolve_delete_hs_bank(bank, hs_bank) -> str:
    """**删除 / 清向量路径**的物理库解析 —— 供日志与兼容用，**绝不阻断删除**。

    ⚠️ 关键事实（2026-09-30 复核，勿再误判）：

      在**当前生产后端 pgvector** 上，``bank`` 形参**不参与删除**。
      ``PgVectorStore.delete`` 自 **FIX-P2-G1（``20a0ef7``，2026-09-16）** 起
      执行 ``DELETE FROM vector_chunks WHERE doc_id = $1`` —— doc_id 是 UUID
      （全局唯一），bank 只是冗余属性。旧实现按 ``(doc_id, bank)`` 二元条件删，
      才是孤儿向量的**复发源**（文档换 bank 后旧 bank 向量删不掉）。

      ⇒ 「哨兵 ``kb`` 当库名 → 从错的库删 → 真库残留孤儿」这个曾经的隐患
      **在前序修复后已不可能发生**。故本函数**不得**引入 fail-fast / 422 /
      跳过清理等阻断逻辑：那会把「旧代码按 doc_id 能正确删掉的行」变成
      「拒绝删 / 不清向量」，属**净回归**。

    职责收窄为：给出一条**尽量可读的库名**用于日志与调用方兼容。

    优先级：① ``hs_bank`` 是**已知物理库**（``KNOWN_HS_BANKS``，含大小写/空白
    归一）→ 直用（**不要求与 bank 自洽**：存量 38 行 ``general``+``kb_checklist``
    的向量就在该库里，且硬校验会锁死这些历史行）；② 否则按 ``bank`` 派生；
    ③ 都不可用 → 返回空串并告警（**不抛错**）。

    >>> resolve_delete_hs_bank("general", "kb")            # 哨兵 → 派生
    'kb_general'
    >>> resolve_delete_hs_bank("general", "kb_checklist")  # 已知库 → 直用
    'kb_checklist'
    >>> resolve_delete_hs_bank("all", "")                  # 都不可用 → 空串
    ''
    """
    hs = str(hs_bank).strip().lower() if hs_bank else ""
    if hs in KNOWN_HS_BANKS:
        # 已知物理库 → 直用；与 bank 不自洽只告警（向量实际写在存量库里）
        try:
            expected = resolve_hs_bank(bank)
            if expected != hs:
                logger.warning(
                    "delete-path bank/hs_bank 不自洽：bank=%r hs_bank=%r 应为 %r "
                    "—— 按存量 hs_bank 记日志（pgvector 删除按 doc_id，bank 不参与）",
                    bank, hs, expected,
                )
        except BankResolutionError as e:
            logger.warning(
                "delete-path bank 不可解析（%s）：按存量 hs_bank=%r 记日志", e, hs,
            )
        return hs
    # 非已知库（空值 / 哨兵 "kb" / 大小写变体 / 垃圾值）→ 尝试按 bank 派生
    try:
        resolved = resolve_hs_bank(bank)
        logger.info(
            "delete-path 存量 hs_bank=%r 非已知物理库 → 按 bank=%r 派生为 %r",
            hs_bank, bank, resolved,
        )
        return resolved
    except BankResolutionError as e:
        logger.warning(
            "delete-path bank/hs_bank 均不可用（bank=%r hs_bank=%r：%s）"
            "—— 返回空串仅用于日志；**不阻断删除**（pgvector 按 doc_id 删除）",
            bank, hs_bank, e,
        )
        return ""

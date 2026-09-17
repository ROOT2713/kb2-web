"""答案结构化服务 —— 把 LLM 回答切分为结构化区块

定位
----
前端 `answerParser.ts` 的**服务端对应实现**。目的是让渲染不再依赖 LLM 输出质量：
服务端先做一次容错解析，把结果以 `answer_blocks` 字段随响应返回，前端优先使用。

与前端实现的差异
----------------
- 前端 `answerParser.ts` 面向"尽量渲染出来"，本模块额外输出 `repair_flags`，
  作为**可统计的质量指标**（哪种坏格式出现得多 → 直接指导 prompt 迭代）；
- 本模块不做任何 HTML 渲染，只产出数据，避免 XSS 面扩大。

设计约束
--------
- 纯函数、零 I/O、零外部依赖（只用标准库 `re`）；
- 解析失败一律降级为单段 `text`，**绝不丢内容**；
- 与前端共享同一套规则常量（`separator_column_mismatch` 等），联调零成本。

代码基线：main `175c546`
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ── 区块类型（与前端 BlockKind 一一对应）──
KIND_CONCLUSION = "conclusion"
KIND_TEXT = "text"
KIND_TABLE = "table"
KIND_NOTE = "note"

# ── 修复标记（可统计的质量指标）──
FIX_NO_SEPARATOR = "no_separator"                        # 表格缺分隔行
FIX_SEPARATOR_COLUMN_MISMATCH = "separator_column_mismatch"  # 分隔行列数与表头不符
FIX_ROW_COLUMN_MISMATCH = "row_column_mismatch"          # 数据行列数与表头不符
FIX_FULLWIDTH_PIPE = "fullwidth_pipe"                    # 全角竖线

# ── 正则（与前端保持同义）──
_CONCLUSION_RE = re.compile(r"^(先给出结论|结论[:：]|综上|总结[:：]|总述)")
_NOTE_RE = re.compile(
    r"^(说明\s*\d+\s*[:：]|说明[:：]|注\s*\d*\s*[:：]|备注[:：]|注意[:：]|⚠️|❗)"
)
# 行首编号：1. / 1、/ (1) / （1） / 【1】 / 1)
_OWN_NUMBER_RE = re.compile(r"^\s*(?:[(（【\[]\s*)?\d{1,2}\s*(?:[.、．)）\]】]|:)\s*\S")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{1,}:?$")
_REF_RE = re.compile(r"[\[【]\s*(?:来源\s*)?(\d{1,2})\s*[\]】]")
_WIDE_PIPE_RE = re.compile(r"｜")


# ══════════════════════════════════════════════════════════════════════
# 基础工具
# ══════════════════════════════════════════════════════════════════════
def _normalize_pipes(line: str) -> str:
    """全角竖线 → 半角；仅当整行以竖线起止时替换，避免误伤正文里的 ｜。"""
    t = line.strip()
    if not t or not re.match(r"^[｜|]", t):
        return line
    return _WIDE_PIPE_RE.sub("|", line)


def _is_pipe_row(line: str) -> bool:
    t = line.strip()
    return t.startswith("|") and t.count("|") >= 3


def _split_cells(line: str) -> List[str]:
    t = line.strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|"):
        t = t[:-1]
    return [c.strip() for c in t.split("|")]


def _is_separator_row(line: str) -> bool:
    t = line.strip()
    if not t.startswith("|"):
        return False
    cells = _split_cells(t)
    if len(cells) < 2:
        return False
    return all(_SEPARATOR_CELL_RE.match(c.replace(" ", "")) for c in cells)


def _align_row(cells: List[str], n: int) -> List[str]:
    if len(cells) == n:
        return cells
    if len(cells) > n:
        return cells[: n - 1] + [" | ".join(cells[n - 1:])]
    return cells + ["—"] * (n - len(cells))


def has_own_numbering(text: str) -> bool:
    """原文是否自带编号（行首 1. / （1） / 1、 等）。"""
    return any(_OWN_NUMBER_RE.match(ln) for ln in text.split("\n"))


def _extract_refs(text: str) -> List[int]:
    refs = sorted({int(m) for m in _REF_RE.findall(text) if 0 < int(m) <= 99})
    return refs


def _split_note_lines(lines: List[str]) -> List[List[str]]:
    """连续多条说明必须拆成独立区块；折行归属上一条。"""
    groups: List[List[str]] = []
    for ln in lines:
        if not ln.strip():
            continue
        if _NOTE_RE.match(ln.strip()) or not groups:
            groups.append([ln])
        else:
            groups[-1].append(ln)
    return groups


# ══════════════════════════════════════════════════════════════════════
# 表格修复
# ══════════════════════════════════════════════════════════════════════
def _repair_table_block(lines: List[str], flags: List[str]) -> List[str]:
    out = list(lines)
    if not out:
        return out
    if len(out) >= 2 and _is_separator_row(out[1]):
        # 有分隔行，但列数可能不匹配
        if len(_split_cells(out[1])) != len(_split_cells(out[0])):
            flags.append(FIX_SEPARATOR_COLUMN_MISMATCH)
            out[1] = _align_separator(out[0], out[1])
        return out
    if not _is_pipe_row(out[0]):
        return out
    flags.append(FIX_NO_SEPARATOR)
    cols = max(2, len(_split_cells(out[0])))
    out.insert(1, "|" + "|".join(["---"] * cols) + "|")
    return out


def _align_separator(header: str, sep: str) -> str:
    cols = max(2, len(_split_cells(header)))
    cells = _split_cells(sep)
    if len(cells) >= cols:
        return sep
    cells = cells + ["---"] * (cols - len(cells))
    return "|" + "|".join(cells) + "|"


# ══════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════
def structure_answer(raw: str) -> List[Dict[str, Any]]:
    """把回答文本切分为结构化区块列表。

    返回一个 list（可直接 JSON 序列化放进 `answer_blocks`）：
        [{"kind": "conclusion", "index": 0, "numbered": False, "text": "...", "refs": []},
         {"kind": "table", "index": 1, "numbered": False,
          "table": {"headers": [...], "rows": [[...]], "raw_row_count": 7,
                    "repair_flags": ["separator_column_mismatch"]},
          "refs": []},
         ...]

    任何异常都会降级为「单段 text」，绝不抛错、绝不丢内容。
    """
    if not raw or not raw.strip():
        return []
    try:
        return _do_parse(raw)
    except Exception as e:  # pragma: no cover — 兜底不可省
        logger.warning("[STRUCTURE] parse failed, fallback to single text block: %s", e)
        return [{
            "kind": KIND_TEXT,
            "index": 1,
            "numbered": has_own_numbering(raw),
            "text": raw,
            "refs": _extract_refs(raw),
        }]


def _collect_table_lines(lines: List[str], start: int) -> int:
    """从 start 开始收集连续表格行（容忍行间空行），返回结束下标。"""
    j = start
    n = len(lines)
    while j < n and (
        _is_pipe_row(lines[j])
        or (lines[j].strip() == "" and j + 1 < n and _is_pipe_row(lines[j + 1]))
    ):
        j += 1
    return j


def _iter_table_rows(fixed: List[str], col_count: int, flags: List[str]) -> List[List[str]]:
    """把修复后的表格行（跳过表头与分隔行）转成规整数据行。"""
    rows: List[List[str]] = []
    for raw_row in fixed[2:]:
        cells = _split_cells(raw_row)
        if len(cells) != col_count and FIX_ROW_COLUMN_MISMATCH not in flags:
            flags.append(FIX_ROW_COLUMN_MISMATCH)
        cells = _align_row(cells, col_count)
        if any(c and c != "—" for c in cells):
            rows.append(cells)
    return rows


def _build_table_block(
    tbl: List[str], index: int
) -> Dict[str, Any]:
    """由原始表格行构造 table 区块（含修复与标记）。"""
    flags: List[str] = []
    if any("｜" in ln for ln in tbl):
        flags.append(FIX_FULLWIDTH_PIPE)
    fixed = _repair_table_block(tbl, flags)
    headers = [h for h in _split_cells(fixed[0]) if h]
    col_count = max(len(headers), 2)
    rows = _iter_table_rows(fixed, col_count, flags)

    return {
        "kind": KIND_TABLE,
        "index": index,
        "numbered": False,
        "text": "",
        "table": {
            "headers": _align_row(headers, col_count),
            "rows": rows,
            "raw_row_count": max(0, len(fixed) - 2),
            "repair_flags": flags,
            "repaired": bool(flags),
        },
        "refs": _extract_refs(" ".join(fixed)),
    }


class _BlockBuilder:
    """把缓冲文本转成区块并维护序号（把 _do_parse 的复杂度抽离出来）。"""

    def __init__(self) -> None:
        self.blocks: List[Dict[str, Any]] = []
        self._seq = 0

    def next_index(self) -> int:
        self._seq += 1
        return self._seq

    def _emit(self, kind: str, text: str, refs: List[int], numbered: bool) -> None:
        self.blocks.append({
            "kind": kind,
            "index": 0 if kind == KIND_CONCLUSION else self.next_index(),
            "numbered": numbered,
            "text": text,
            "refs": refs,
        })

    def table(self, tbl: List[str]) -> None:
        self.blocks.append(_build_table_block(tbl, self.next_index()))

    def flush(self, buf: List[str]) -> None:
        """消费缓冲区：按内容判定 conclusion / note / text 三类区块。"""
        text = "\n".join(buf).strip()
        if not text:
            return
        refs = _extract_refs(text)
        numbered = has_own_numbering(text)
        body = [ln for ln in text.split("\n") if ln.strip()]

        if len(body) == 1 and _CONCLUSION_RE.match(text):
            self._emit(KIND_CONCLUSION, text, refs, numbered)
        elif body and all(_NOTE_RE.match(ln.strip()) for ln in body):
            for grp in _split_note_lines(body):
                note_text = "\n".join(grp).strip()
                if note_text:
                    self._emit(
                        KIND_NOTE, note_text,
                        _extract_refs(note_text), has_own_numbering(note_text),
                    )
        else:
            self._emit(KIND_TEXT, text, refs, numbered)


def _do_parse(raw: str) -> List[Dict[str, Any]]:
    lines = [
        _normalize_pipes(ln)
        for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    builder = _BlockBuilder()
    buf: List[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if _is_pipe_row(line):
            j = _collect_table_lines(lines, i)
            tbl = [ln for ln in lines[i:j] if ln.strip()]
            if len(tbl) >= 2:
                builder.flush(buf)
                buf = []
                builder.table(tbl)
                i = j
                continue

        if line.strip():
            buf.append(line)
        else:
            builder.flush(buf)
            buf = []
        i += 1

    builder.flush(buf)
    return builder.blocks


def structure_stats(blocks: List[Dict[str, Any]]) -> Dict[str, int]:
    """从区块列表统计各类型数量与修复次数（供日志/看板使用）。"""
    st = {"table": 0, "text": 0, "note": 0, "conclusion": 0, "repaired": 0}
    for b in blocks:
        k = b.get("kind")
        if k in st:
            st[k] += 1
        if k == KIND_TABLE and (b.get("table") or {}).get("repaired"):
            st["repaired"] += 1
    return st


__all__ = [
    "structure_answer", "structure_stats", "has_own_numbering",
    "KIND_CONCLUSION", "KIND_TEXT", "KIND_TABLE", "KIND_NOTE",
    "FIX_NO_SEPARATOR", "FIX_SEPARATOR_COLUMN_MISMATCH",
    "FIX_ROW_COLUMN_MISMATCH", "FIX_FULLWIDTH_PIPE",
]

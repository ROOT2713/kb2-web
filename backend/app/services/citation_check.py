"""引用真实性校验（citation check）—— 答案生成后、写缓存【之前】的程序化闸门。

零 LLM、纯正则 + 集合运算，微秒级。目的：挡住 LLM 编造来源（幻觉引用）——
这类缺陷最危险，因为用户会拿「来源」去核对。

来源：R7 交付包（`A2-2_引用真实性校验citation_check.py`）的**采纳版**，
按本仓纪律做了三件事：① 逐条复核其「R7 对抗审计修正记录」的宣称；
② 补行为测试 + 突变核验；③ 显式声明**未接线**（见文件末 WIRING 段）。

★ 采纳时的复核结论（勿删）：
  · 「原 _CITE_FILE 用 [^（）()] 排除内层括号 ⇒ 含『（试行）』的文件名
    零提取」——**成立**。已保留非贪婪修正形态，并有回归锚用例。
  · 「原测试 3 空洞通过（cited=set() ⇒ ok=True 假绿）」——**成立**。
    本仓用例改为先断言 cited 非空。
  · 「顿号粘连正文」——**成立**（`来源：A、B 两份` 原会把「B 两份…」并入）。
  · 【未修，如实登记】形态级校验无法区分「文档引用」与「事实转引」：
    `《网络安全法》` 这类法条转引会成为 unknown ⇒ 误报。R7 定的上线前置
    是「真实语料回放统计 false-positive 率，>5% 先收紧 prompt 引用格式」
    —— 这正是本模块**暂不接线**的原因。

★ 形态级防线声明（能力边界，勿当成完备防线）：
  · 能挡：编造《书名》、编造「来源：X」、编造括号文件名引用；
  · 不挡（已知漏报）：无标注形态（「依据 GB/T 39786 第 6.1 条」）、
    英文 `Source:` 前缀、无扩展名的括号引用、裸文件名。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Set

# 引用标注提取形态集：
#  ① 书名号《文档名》——核心形态，始终启用
#  ② 来源段「来源：X」——捕获排除顿号/逗号/句读（防粘连正文），始终启用
#  ③ 括号 + 扩展名（X.pdf 等）——非贪婪，允许文件名含内层括号
#  ④ 【文档名】——默认关闭（中文【】歧义大，`enable_bracket=True` 才启用）
_CITE_BOOK = re.compile(r"《([^《》]{2,120})》")
_CITE_SOURCE = re.compile(r"来源[:：]\s*([^\n，。；,;、]{2,120})")
_CITE_FILE = re.compile(r"[（(](.+?\.(?:md|pdf|docx|txt))[）)]", re.IGNORECASE)
_CITE_BRACKET = re.compile(r"【([^【】]{2,120})】")


def _normalize(name: str) -> str:
    """归一化：去扩展名、去路径、去空白（库内标题会被规范化重写，故做宽松匹配）。"""
    name = re.sub(r"\.(md|pdf|docx|txt)$", "", name.strip(), flags=re.IGNORECASE)
    name = name.split("/")[-1].split("\\")[-1]
    return re.sub(r"\s+", "", name)


@dataclass
class CitationReport:
    ok: bool
    skipped: bool = False                            # known 空集（检索为空）时 True
    cited: Set[str] = field(default_factory=set)     # 归一化后的全部引用
    unknown: Set[str] = field(default_factory=set)   # context 中找不到的引用


def check_citations(
    answer: str,
    context_doc_names: Iterable[str],
    enable_bracket: bool = False,
) -> CitationReport:
    """校验 answer 中的来源标注是否都在 context 提供的文档集合内。

    context_doc_names：本次 prompt 的文档内容段所对应的文档名集合
    （调用方从 retrieval 结果取 title，**勿传全库名单**——传全库会把
    编造引用也放过）。
    """
    known = {_normalize(n) for n in context_doc_names if n}
    if not known:
        # 检索为空（兜底路径）时无引用可校验，不拦截合法答案
        return CitationReport(ok=True, skipped=True)

    cited: Set[str] = set()
    patterns = [_CITE_BOOK, _CITE_SOURCE, _CITE_FILE]
    if enable_bracket:
        patterns.append(_CITE_BRACKET)
    for pat in patterns:
        for m in pat.finditer(answer or ""):
            cited.add(_normalize(m.group(1)))

    unknown = {c for c in cited if c not in known}
    # 无引用标注 ⇒ 不判失败（兜底型回答本就没有来源段）；
    # 有引用且全部命中 ⇒ ok；有引用且存在未命中 ⇒ 不 ok
    return CitationReport(ok=not unknown, cited=cited, unknown=unknown)


# ── WIRING（★ 本模块当前**未接线**，这是有意的）─────────────────────
# R7 方案给的接线点是两处（同一函数；只挂一处会重演「双保险漂移」）：
#   ① multi_hypothesis_answer() 返回后、写缓存前；
#   ② 单路生成路径（fallback 分支）返回后、写缓存前。
# 失败处置：answer_meta["degraded"] = True（复用既有「degraded 不入缓存」铁律）。
#
# 为什么暂不接线（不是偷懒，是三个硬前置）：
#   ① **误报面实测很高**：在真实知识库正文层抽样（400 个 parent_chunk）——
#      共 182 处《》引用、去重 99 个，其中 **93 个（93.9%）不在文档名集合内**，
#      且绝大多数是正文里引用的**标准名**（《建筑隔声评价标准》10x、
#      《声环境质量标准》6x、《地铁设计规范》5x…）。远超 R7 自定的 5% 门槛。
#      这一层是 context 的近似；但 LLM 的引用风格通常复制自 context，故
#      直接接线极可能让大量正常答案被标 degraded 且不入缓存（可用性退化）。
#   ② **答案层无法离线标定**：系统**不保留答案文本**——`query_cache` 仅 3 条、
#      `query_log` 2065 行只存 answer_length。⇒ R7「真实语料回放一周」这一
#      前置在当前数据下**无法事后补测**，只能靠前向观测。
#      ⇒ 若接线，应采用**观察模式**（只 `logger.warning` 记录 unknown 集合，
#      **不**置 degraded、不影响缓存），跑一周拿到真实占比后再决定是否收紧。
#      ★ 这比 R7 原方案（首版即置 degraded 不入缓存）更稳：把「标定」与
#      「改变可用性」解耦，避免用一次不可回撤的退化去换标定数据。
#   ③ **命中要求调用方从 retrieval 取 title 集合**，需确认 generation.py
#      里两处返回路径都能拿到「本次实际进 prompt 的文档集」，而非全库名单。
# 前置满足后再接线，并须（按本仓纪律）配突变核验 + 重启授权。

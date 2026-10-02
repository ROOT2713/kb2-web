"""_query_title_match 单测 —— 拒答闸门「精确标题匹配逃生口」修复。

缺陷背景（2026-10-02）：
  L1.5 substance gate / L2 has_exact_match 原先用整串子串比对标题
  （``q_lower in dn or dn in q_lower``），对「地名 + 空格 + 主题」这类
  最自然的提问方式完全失效 —— 「佛山 概算编制指南」与真实标题
  「佛山市市级政务信息化项目概算编制指南（2022版）」互不包含，
  于是检索已召回的文档被误判「无可靠答案」→ 接口返回 0 条来源。

  修复后判定（阈值 1.00）= 查询的实义分词必须**全部**出现在同一标题里，
  且地名一致。取 1.00 而非 0.80 的原因见源码注释：0.80 会误放
  「江门 政务 信息化 项目 概算 编制 指南」（0.857）等拼接问法，
  即拿佛山文档回答江门问题（CC 评审实测复现）。
"""
from pathlib import Path

import pytest

from app.api import query_engine as qe
from app.api.query_engine import (
    _LOCATION_RE,
    _TITLE_COVERAGE_THRESHOLD,
    _query_title_match,
)
from app.utils.tokenizer import tokenize

FOSHAN_TITLE = "佛山市市级政务信息化项目概算编制指南（2022版）"
GUANGZHOU_TITLE = "广州市政务信息化项目管理办法（2022年修订稿）"


def _match(q: str, title: str) -> bool:
    """按生产调用形态算出 tokens/locs 再判定。"""
    ql = q.lower()
    return _query_title_match(ql, title.lower(),
                              tokenize(ql), _LOCATION_RE.findall(ql))


class TestExistingBehaviourKept:
    """原有整串子串行为必须原样保留（最短路径，不得回退）。"""

    def test_query_is_substring_of_title(self):
        assert _match("概算编制指南", FOSHAN_TITLE) is True

    def test_title_is_substring_of_query(self):
        assert _match("请问电子政务工程造价指导书（2019年）讲了什么",
                      "电子政务工程造价指导书（2019年）") is True


class TestTheReportedDefect:
    """本案缺陷：地名 + 空格 + 主题 → 修复前 0 来源。"""

    @pytest.mark.parametrize("q", [
        "佛山 概算编制指南",      # 空格分隔
        "佛山市 概算编制指南",    # 带「市」
        "佛山概算编制指南",       # 无分隔（标题中间隔了「市市级政务信息化项目」）
        "佛山的概算编制指南",     # 带助词「的」
        "佛山概算编制指南 2022版",
    ])
    def test_foshan_variants_match(self, q):
        assert _match(q, FOSHAN_TITLE) is True, q

    @pytest.mark.parametrize("city", ["广州", "东莞", "深圳", "上海"])
    def test_other_city_same_topic_rejected(self, city):
        """库里只有佛山的概算编制指南 —— 其他城市必须继续拒答，不得张冠李戴。"""
        assert _match(f"{city} 概算编制指南", FOSHAN_TITLE) is False, city

    # ── CC 评审反例（阈值 0.80 时会被误放；这三条是改 1.00 的直接依据）──

    @pytest.mark.parametrize("city", ["江门", "惠州", "汕头", "湛江"])
    def test_unknown_city_not_in_location_list(self, city):
        """地名正则的城市清单不全 —— 清单外城市靠「实义词全命中」兜住。"""
        assert _match(f"{city} 概算编制指南", FOSHAN_TITLE) is False, city

    def test_cc_counterexample_a_unknown_city_plus_generic_words(self):
        """0.857 覆盖率 + 地名正则认不出「江门」→ 0.80 会误放。"""
        assert _match("江门 政务 信息化 项目 概算 编制 指南", FOSHAN_TITLE) is False

    def test_cc_counterexample_b_irrelevant_topic_word(self):
        """无关主题词混入（0.800）→ 不得放行。"""
        assert _match("佛山 概算编制指南 消防", FOSHAN_TITLE) is False

    def test_cc_counterexample_c_extra_city(self):
        assert _match("佛山 江门 概算编制指南", FOSHAN_TITLE) is False


class TestGuards:
    def test_empty_doc_name(self):
        assert _match("佛山 概算编制指南", "") is False

    def test_empty_query(self):
        """空查询曾被 ``"" in title`` 判定为精确命中 → 必须显式拒绝。"""
        assert _query_title_match("", FOSHAN_TITLE, [], []) is False

    def test_no_tokens_after_filter(self):
        """全单字符 → tokens 为空 → 不得放行（防 ZeroDivision 且防误放）。"""
        assert _match("的 了 在", FOSHAN_TITLE) is False

    def test_threshold_boundary_below(self):
        """4 词命中 3 词 = 0.75 < 1.00 → 拒。"""
        assert _match("编制 指南 概算 消防", FOSHAN_TITLE) is False

    def test_threshold_value_locked(self):
        assert _TITLE_COVERAGE_THRESHOLD == 1.00

    def test_location_guard_blocks_when_topics_all_hit(self):
        """覆盖率 100% 但查询地名不在标题 → 必须被地名一致性拦下。

        直接传入手工 tokens 以隔离「地名护栏」这一条独立断言
        （否则会被覆盖率断言抢先拦住，测不到护栏本身）。
        """
        assert _query_title_match(
            "广州 概算编制指南", "广东省佛山市概算编制指南",
            ["概算", "编制", "指南"], ["广州"],
        ) is False

    def test_location_guard_passes_when_consistent(self):
        assert _query_title_match(
            "佛山 概算编制指南", "广东省佛山市概算编制指南",
            ["概算", "编制", "指南"], ["佛山"],
        ) is True

    def test_standard_number_query(self):
        assert _match("GB 50174 数据中心", "【机】GB 50174-2017 数据中心设计规范")

    @pytest.mark.parametrize("q", [
        "广州 政务信息化项目管理办法",
        "东莞 造价指南",
        "等保测评 检查标准",
        "粤府办 2020 9号",
        "电子政务工程造价指导书",
    ])
    def test_real_kb_docs_still_match(self, q):
        """阳性对照：库里确有对应文档的自然问法，不得被 1.00 阈值误伤。"""
        import sqlite3
        con = sqlite3.connect("file:/home/ubuntu/kb-web/data/kb.db?mode=ro",
                              uri=True)
        titles = [r[0] for r in con.execute(
            "SELECT title FROM documents WHERE status='active' "
            "AND searchable=1 AND title IS NOT NULL")]
        con.close()
        assert any(_match(q, t) for t in titles), q


class TestWiringSourceLock:
    """源码防回退锁：两处逃生口必须调用新辅助，旧整串写法不得残留。"""

    def test_helper_wired_at_both_gates(self):
        src = Path(qe.__file__).read_text(encoding="utf-8")
        # 1 处定义 + L1.5/L2 两处调用
        assert src.count("_query_title_match(") == 3

    def test_old_inline_substring_pattern_gone(self):
        src = Path(qe.__file__).read_text(encoding="utf-8")
        assert "q_lower in dn or dn in q_lower" not in src
        assert ("q_lower in doc_name.lower() or doc_name.lower() in q_lower"
                not in src)

    def test_location_regex_has_single_source(self):
        src = Path(qe.__file__).read_text(encoding="utf-8")
        assert src.count("_LOCATION_RE = re.compile(") == 1
        assert src.count("_location_pattern = _LOCATION_RE") == 1

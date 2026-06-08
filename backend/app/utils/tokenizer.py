"""Tokenizer — jieba-based Chinese tokenization for BM25.

Ported from: kb-web server.py _tokenize() L1366-L1369, _expand_keywords() L1371-L1400,
             extract_keyword_snippet() L1402-L1424
"""

import re
from typing import List

import jieba


def tokenize(text: str) -> List[str]:
    """jieba 分词，去掉单字符和空白"""
    return [w for w in jieba.cut(text) if len(w.strip()) > 1]


def expand_keywords(keywords: List[str]) -> List[str]:
    """将长compound关键词拆分为子词，用于模糊匹配。

    例如: "接地电阻的测试方法" → ["接地", "电阻", "测试", "方法", "接地电阻", "测试方法"]
    去掉"的/了/和/与/在/是"等停用词。
    """
    # [P2-3] 保护金额模式不被拆分
    amounts_found = {}
    protected = []
    for kw in keywords:
        m = re.match(r'^(\d+(?:\.\d+)?)\s*(万|万元|百万|亿|元)$', kw)
        if m:
            placeholder = f'__AMT_{len(amounts_found)}__'
            amounts_found[placeholder] = kw
            protected.append(placeholder)
        else:
            protected.append(kw)

    STOP = {"的", "了", "和", "与", "在", "是", "对", "被", "将", "把", "从", "到", "为"}
    expanded = set(protected)
    for kw in protected:
        if len(kw) > 4:
            # jieba再分词
            subs = [w for w in jieba.cut(kw) if len(w.strip()) > 1 and w not in STOP]
            expanded.update(subs)
    # [P2-3] 恢复金额占位符
    results = list(expanded)
    results = [amounts_found.get(r, r) for r in results]
    return results


def extract_keyword_snippet(text: str, keywords: list, context_chars: int = 500) -> str:
    """从文本中提取包含最多关键词重叠的片段，而非第一个匹配的片段"""
    best_snippet = text[:context_chars * 2]
    best_score = 0

    for kw in keywords:
        pos = text.find(kw)
        if pos >= 0:
            start = max(0, pos - context_chars)
            end = min(len(text), pos + len(kw) + context_chars)
            snippet = text[start:end]
            # 计算该片段中命中的关键词数量
            score = sum(1 for k in keywords if k in snippet)
            if score > best_score:
                best_score = score
                best_snippet = snippet
                if start > 0:
                    best_snippet = "..." + best_snippet
                if end < len(text):
                    best_snippet = best_snippet + "..."

    return best_snippet

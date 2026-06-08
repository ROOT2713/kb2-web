"""Tokenizer — jieba-based Chinese tokenization for BM25.

Ported from: kb-web server.py _tokenize() L1366-L1369, _expand_keywords() L1371-L1400
"""

from typing import List


def tokenize(text: str) -> List[str]:
    """Tokenize Chinese text using jieba."""
    try:
        import jieba
        return list(jieba.cut(text))
    except ImportError:
        # Fallback: whitespace split
        return text.split()


def expand_keywords(keywords: List[str]) -> List[str]:
    """Expand keyword list with synonyms."""
    # TODO: Port _expand_keywords() with synonym_map integration
    return keywords

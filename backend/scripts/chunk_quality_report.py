#!/usr/bin/env python3
"""
chunk_quality_report.py — chunk 级质量评估报告

用途：每次 chunking 参数调整后运行，量化评估切分质量。
支持两种模式：
  1. 直接对 chunking 函数输出跑（开发/测试）
  2. 从 DB 读取已存文档跑（生产验证）

指标：
  - 边界断裂率：chunk 不以 。！？；\\n 结尾的占比
  - 小碎片率：<100 字 chunk 占比
  - 大块率：>2500 字 chunk 占比（超过推荐值）
  - 表格完整性：含 <tr> 的 chunk 中，tr 标签闭合率
  - 标题匹配度：父块前 80 字含文档标题关键词的比例
  - embedding 冗余率：相邻 chunk 的 overlap 超出设定值的占比

用法：
  python3 scripts/chunk_quality_report.py                    # DB 模式
  python3 scripts/chunk_quality_report.py --text="..."       # 直接模式
"""

import re
import sys
import os
from collections import Counter

# ── 指标函数 ──

def boundary_breakage_rate(chunks: list) -> tuple[float, list]:
    """边界断裂率：chunk 不以句子结束符结尾的占比"""
    sentence_enders = set(['。', '！', '？', '；', '\n', '.', '!', '?', '>', '】', '）', ')', '】'])
    broken = []
    for c in chunks:
        text = c.get("child", c.get("text", ""))
        if not text.strip():
            continue
        last_char = text.rstrip()[-1] if text.rstrip() else ''
        if last_char not in sentence_enders:
            broken.append(text[-30:] if len(text) > 30 else text)
    rate = len(broken) / max(len(chunks), 1)
    return rate, broken[:10]  # 最多展示 10 个断裂样本


def small_fragment_rate(chunks: list, threshold: int = 100) -> tuple[float, list]:
    """小碎片率： <threshold 字的 chunk 占比"""
    small = []
    for c in chunks:
        text = c.get("child", c.get("text", ""))
        if not text.strip():
            continue
        if len(text) < threshold:
            small.append(text[:50])
    rate = len(small) / max(len(chunks), 1)
    return rate, small[:10]


def large_chunk_rate(chunks: list, threshold: int = 2500) -> tuple[float, list]:
    """大块率：>threshold 字的 chunk 占比"""
    large = []
    for c in chunks:
        text = c.get("child", c.get("text", ""))
        if not text.strip():
            continue
        if len(text) > threshold:
            large.append(len(text))
    rate = len(large) / max(len(chunks), 1)
    return rate, large[:10]


def table_integrity(chunks: list) -> tuple[float, list]:
    """表格完整性：含 <tr> 的 chunk 中标签闭合率"""
    bad = []
    total_table_chunks = 0
    for c in chunks:
        text = c.get("child", c.get("text", ""))
        open_tr = text.count('<tr')
        close_tr = text.count('</tr>')
        if open_tr == 0 and close_tr == 0:
            continue
        total_table_chunks += 1
        if open_tr != close_tr:
            bad.append({"text": text[:60], "open": open_tr, "close": close_tr})
    score = 1.0 - (len(bad) / max(total_table_chunks, 1))
    return score, bad[:10]


def title_match_rate(chunks: list) -> tuple[float, int, int]:
    """标题匹配度：parent/section 含文档标题关键词的占比"""
    match_count = 0
    total = 0
    for c in chunks:
        hint = c.get("section_hint", "")
        if not hint or hint == "":
            continue
        total += 1
        # 检查 section_hint 是否 >= 2 个词（有意义的标题）
        if len(hint.split()) >= 2:
            match_count += 1
    rate = match_count / max(total, 1)
    return rate, match_count, total


def embedding_redundancy(chunks: list, expected_overlap_pct: float = 0.15) -> tuple[float, list]:
    """embedding 冗余率：相邻 chunk 间实际重叠超出预期的比例"""
    anomalous = []
    for i in range(1, len(chunks)):
        prev = chunks[i-1].get("child", chunks[i-1].get("text", ""))
        curr = chunks[i].get("child", chunks[i].get("text", ""))
        if not prev or not curr:
            continue
        # 实际重叠量：prev 末尾与 curr 开头相同的字符数
        overlap_len = 0
        for j in range(min(len(prev), len(curr)), 0, -1):
            if prev[-j:] == curr[:j]:
                overlap_len = j
                break
        overlap_pct = overlap_len / max(len(curr), 1)
        # 超过设置值 5% 以上视为异常
        if overlap_pct > expected_overlap_pct + 0.05:
            anomalous.append({
                "i": i,
                "overlap_chars": overlap_len,
                "overlap_pct": round(overlap_pct * 100, 1),
                "prev_end": prev[-30:],
                "curr_start": curr[:30],
            })
    rate = len(anomalous) / max(len(chunks) - 1, 1)
    return rate, anomalous[:5]


# ── 报告生成 ──

def generate_report(chunks: list, title: str = "未命名", expected_overlap: float = 0.15) -> dict:
    """生成完整质量报告"""

    b_rate, b_samples = boundary_breakage_rate(chunks)
    s_rate, s_samples = small_fragment_rate(chunks)
    l_rate, l_samples = large_chunk_rate(chunks)
    t_score, t_bad = table_integrity(chunks)
    tm_rate, tm_matched, tm_total = title_match_rate(chunks)
    r_rate, r_anomalies = embedding_redundancy(chunks, expected_overlap)

    total_chars = sum(len(c.get("child", c.get("text", ""))) for c in chunks)
    total_child_chars = sum(len(c.get("child", "")) for c in chunks) if "child" in chunks[0] else total_chars

    # 综合评分 (0-100)
    score = 100.0
    score -= b_rate * 50       # 边界断裂扣分
    score -= s_rate * 30       # 小碎片扣分
    score -= l_rate * 20       # 大块扣分
    score -= (1 - t_score) * 30  # 表格断裂扣分
    score = max(0, score)

    report = {
        "title": title,
        "stats": {
            "total_chunks": len(chunks),
            "total_chars": total_child_chars,
            "avg_chunk_size": round(total_child_chars / max(len(chunks), 1), 1),
            "median_chunk_size": round(sorted([len(c.get("child", c.get("text", ""))) for c in chunks])[len(chunks)//2], 1) if chunks else 0,
        },
        "metrics": {
            "boundary_breakage_rate": {
                "value": round(b_rate * 100, 1),
                "threshold": "< 10% ✅" if b_rate < 0.10 else "< 10% ❌",
                "grade": "✅" if b_rate < 0.10 else ("⚠️" if b_rate < 0.20 else "❌"),
                "samples": b_samples[:5],
            },
            "small_fragment_rate": {
                "value": round(s_rate * 100, 1),
                "threshold": "< 5%",
                "grade": "✅" if s_rate < 0.05 else ("⚠️" if s_rate < 0.10 else "❌"),
                "samples": s_samples[:5],
            },
            "large_chunk_rate": {
                "value": round(l_rate * 100, 1),
                "threshold": "< 10%",
                "grade": "✅" if l_rate < 0.10 else ("⚠️" if l_rate < 0.20 else "❌"),
                "samples": [f"{c}字" for c in l_samples[:5]],
            },
            "table_integrity": {
                "value": round(t_score * 100, 1),
                "threshold": "100%",
                "grade": "✅" if t_score >= 0.99 else ("⚠️" if t_score >= 0.90 else "❌"),
                "bad_chunks": len(t_bad),
                "samples": t_bad[:3],
            },
            "title_match_rate": {
                "value": round(tm_rate * 100, 1),
                "matched": tm_matched,
                "total": tm_total,
                "grade": "✅" if tm_rate >= 0.80 else ("⚠️" if tm_rate >= 0.60 else "❌"),
            },
            "embedding_redundancy": {
                "value": round(r_rate * 100, 1),
                "threshold": f"< 5% (overlap>{expected_overlap*100+5:.0f}%)",
                "grade": "✅" if r_rate < 0.05 else ("⚠️" if r_rate < 0.10 else "❌"),
                "samples": r_anomalies[:3],
            },
        },
        "score": round(score, 1),
        "score_band": "优秀" if score >= 90 else ("良好" if score >= 75 else ("一般" if score >= 60 else "差")),
    }
    return report


def print_report(report: dict):
    """格式化打印报告"""
    r = report
    print("=" * 60)
    print(f"  切片质量报告: {r['title']}")
    print("=" * 60)
    print(f"  综合评分: {r['score']} / 100  ({r['score_band']})")
    print(f"  Chunks: {r['stats']['total_chunks']} | 总字数: {r['stats']['total_chars']} | "
          f"平均: {r['stats']['avg_chunk_size']} | 中位: {r['stats']['median_chunk_size']}")
    print("-" * 60)
    for key, m in r["metrics"].items():
        label = key.replace("_", " ").title()
        grade = m["grade"]
        value = m["value"]
        threshold = m.get("threshold", "")
        print(f"  {grade} {label}: {value}%  ({threshold})")
        if m.get("samples"):
            for s in m["samples"][:3]:
                print(f"     → {s}")
    print("=" * 60)


# ── DB 模式 ──
def load_from_db(limit: int = 5) -> list:
    """从 DB 读取 parent_chunks 数据，重新用当前参数切分以验证"""
    os.environ.setdefault('JWT_SECRET', 'test')
    os.environ.setdefault('DATABASE_URL', 'sqlite:///data/kb2.db')

    script_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = script_dir
    if not os.path.exists(os.path.join(backend_dir, 'app')):
        backend_dir = os.path.join(backend_dir, '..')
    sys.path.insert(0, backend_dir)

    from app.config import settings
    from app.models.database import SessionLocal
    from app.models.document import Document, ParentChunk
    from app.services.chunking import parent_child_chunk

    db = SessionLocal()
    try:
        docs = db.query(Document).order_by(Document.updated_at.desc()).limit(limit).all()
        doc_reports = []
        for doc in docs:
            parents = db.query(ParentChunk).filter(
                ParentChunk.doc_id == doc.id
            ).order_by(ParentChunk.parent_idx).all()
            if not parents:
                continue
            # 用 parent 文本组合后重新 chunk，验证当前参数下质量
            combined = "\n\n".join(p.parent_text for p in parents)
            chunk_list = parent_child_chunk(
                combined,
                child_size=settings.default_chunk_size,
                parent_size=settings.default_parent_size,
                overlap=settings.chunk_overlap,
                doc_title=doc.title or doc.filename or f"doc_{doc.id}",
            )
            title = f"{doc.title or doc.filename} ({doc.id})"
            report = generate_report(chunk_list, title=title)
            doc_reports.append(report)

        # 整体报告
        if doc_reports:
            return doc_reports
        return None
    finally:
        db.close()


if __name__ == "__main__":
    if "--text" in sys.argv:
        idx = sys.argv.index("--text") + 1
        text = sys.argv[idx] if idx < len(sys.argv) else sys.stdin.read()
        _mode = "direct"
    elif "--db" in sys.argv:
        _mode = "db"
    else:
        _mode = "direct"
        # Read from stdin if available
        if not sys.stdin.isatty():
            text = sys.stdin.read()
        else:
            text = None

    if _mode == "direct" and text:
        os.environ.setdefault('JWT_SECRET', 'test')
        os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from app.config import settings
        from app.services.chunking import parent_child_chunk

        result = parent_child_chunk(
            text, child_size=settings.default_chunk_size,
            parent_size=settings.default_parent_size,
            overlap=settings.chunk_overlap,
            doc_title="直接模式"
        )
        report = generate_report(result, title="直接模式")
        print_report(report)
    elif _mode == "db":
        reports = load_from_db(limit=5)
        if reports:
            for dr in reports:
                print_report(dr)
        else:
            print("❌ 未读取到文档")
    else:
        print("用法: python3 scripts/chunk_quality_report.py [--text '...' | --db | < stdin")
        sys.exit(1)

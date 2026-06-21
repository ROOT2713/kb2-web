"""OKF Quality Gates — 三级质量门禁服务。

P1-3: 文档质量检查，分三级门禁：

G1 (Format): 文件格式、编码、基本结构
  - 文件大小 > 0
  - 文本内容长度 > 100 字符
  - 编码正确（无乱码）
  - 基本章节结构存在

G2 (Completeness): 内容完整性
  - 有标题
  - 有 bank 分类
  - 有 doc_type
  - chunk 数量 > 0
  - concept 已生成

G3 (Consistency): 跨文档一致性
  - 无重复标题（同 bank 下）
  - 标准号格式正确（GB 标准）
  - 引用关系完整（如有 superseded_by 则目标存在）
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.concept import Concept

logger = logging.getLogger(__name__)


class GateResult:
    """单个门禁的检查结果。"""

    def __init__(self, level: str, passed: bool, score: float, issues: List[str]):
        self.level = level
        self.passed = passed
        self.score = score  # 0.0 - 1.0
        self.issues = issues

    def to_dict(self) -> Dict:
        return {
            "gate": self.level,
            "passed": self.passed,
            "score": round(self.score, 3),
            "issues": self.issues,
        }


def check_document(
    db: Session,
    doc_id: str,
    gates: str = "G1,G2,G3",
) -> Dict:
    """对单个文档执行质量门禁检查。

    Args:
        db: 数据库 session
        doc_id: 文档 ID
        gates: 要执行的门禁级别（逗号分隔）

    Returns:
        {
            "doc_id": str,
            "title": str,
            "overall_passed": bool,
            "overall_score": float,
            "gates": [GateResult, ...],
        }
    """
    doc = db.query(Document).filter(Document.doc_id == doc_id).first()
    if not doc:
        return {"error": "Document not found"}

    gate_levels = [g.strip().upper() for g in gates.split(",")]
    results = []

    if "G1" in gate_levels:
        results.append(_check_g1_format(doc))
    if "G2" in gate_levels:
        results.append(_check_g2_completeness(db, doc))
    if "G3" in gate_levels:
        results.append(_check_g3_consistency(db, doc))

    overall_passed = all(r.passed for r in results)
    overall_score = sum(r.score for r in results) / len(results) if results else 0.0

    # 记录到 quality_gate_log
    _log_gate_result(db, doc_id, results)

    return {
        "doc_id": doc_id,
        "title": doc.title,
        "overall_passed": overall_passed,
        "overall_score": round(overall_score, 3),
        "gates": [r.to_dict() for r in results],
    }


def check_all_documents(
    db: Session,
    gates: str = "G1,G2",
    limit: int = 100,
) -> Dict:
    """批量检查所有活跃文档。"""
    docs = db.query(Document).filter(
        Document.status == "active"
    ).limit(limit).all()

    results = []
    passed_count = 0
    failed_count = 0

    for doc in docs:
        result = check_document(db, doc.doc_id, gates)
        if "error" not in result:
            results.append(result)
            if result["overall_passed"]:
                passed_count += 1
            else:
                failed_count += 1

    return {
        "total_checked": len(results),
        "passed": passed_count,
        "failed": failed_count,
        "pass_rate": round(passed_count / len(results), 3) if results else 0.0,
        "results": results,
    }


def _check_g1_format(doc: Document) -> GateResult:
    """G1: 格式检查。"""
    issues = []
    score = 1.0

    # 检查 1: 文件大小/内容
    if not doc.original_text_length or doc.original_text_length < 100:
        issues.append("内容过短（<100 字符）")
        score -= 0.3

    # 检查 2: 基本结构（有 chunk）
    if not doc.chunk_count or doc.chunk_count == 0:
        issues.append("无分块（chunk_count=0）")
        score -= 0.3

    # 检查 3: title 不为空
    if not doc.title or not doc.title.strip():
        issues.append("标题为空")
        score -= 0.2

    # 检查 4: bank 有效
    valid_banks = {"general", "business", "law", "standard", "tech", "methodology",
                   "standards", "governance", "operations", "learning", "ephemeral"}
    if doc.bank and doc.bank not in valid_banks:
        issues.append(f"未知 bank: {doc.bank}")
        score -= 0.1

    return GateResult(
        level="G1",
        passed=len(issues) == 0,
        score=max(0.0, score),
        issues=issues,
    )


def _check_g2_completeness(db: Session, doc: Document) -> GateResult:
    """G2: 完整性检查。"""
    issues = []
    score = 1.0

    # 检查 1: 有 concept_id
    if not doc.concept_id:
        issues.append("缺少 concept_id")
        score -= 0.3

    # 检查 2: 有 domain
    if not doc.domain:
        issues.append("缺少 domain")
        score -= 0.2

    # 检查 3: 有 doc_type
    if not doc.doc_type or doc.doc_type == "generic":
        issues.append("doc_type 为 generic（建议明确类型）")
        score -= 0.1

    # 检查 4: concept 已生成
    concept_count = db.query(Concept).filter(
        Concept.doc_id == doc.doc_id,
        Concept.status == "active",
    ).count()
    if concept_count == 0:
        issues.append("无 concept 记录")
        score -= 0.3

    # 检查 5: chunk_count 与 concept_count 匹配
    if doc.chunk_count and concept_count > 0:
        ratio = concept_count / doc.chunk_count
        if ratio < 0.3:
            issues.append(f"concept/chunk 比率过低 ({concept_count}/{doc.chunk_count})")
            score -= 0.1

    return GateResult(
        level="G2",
        passed=len(issues) == 0,
        score=max(0.0, score),
        issues=issues,
    )


def _check_g3_consistency(db: Session, doc: Document) -> GateResult:
    """G3: 一致性检查。"""
    issues = []
    score = 1.0

    # 检查 1: 标准号格式（GB 标准）
    if doc.doc_type == "gb_standard":
        if not re.search(r'GB[/]?[TSC]?\s*[\d]+', doc.title or ""):
            issues.append("GB 标准文档标题缺少标准号")
            score -= 0.2

    # 检查 2: superseded_by 引用存在
    if doc.superseded_by:
        target = db.query(Document).filter(
            Document.doc_id == doc.superseded_by
        ).first()
        if not target:
            issues.append(f"superseded_by 引用不存在: {doc.superseded_by}")
            score -= 0.3

    # 检查 3: supersedes 引用存在
    if doc.supersedes:
        target = db.query(Document).filter(
            Document.doc_id == doc.supersedes
        ).first()
        if not target:
            issues.append(f"supersedes 引用不存在: {doc.supersedes}")
            score -= 0.3

    # 检查 4: 同 bank 下无重复标题
    if doc.title:
        dup = db.query(Document).filter(
            Document.bank == doc.bank,
            Document.title == doc.title,
            Document.doc_id != doc.doc_id,
            Document.status == "active",
        ).first()
        if dup:
            issues.append(f"同 bank 下存在重复标题: {dup.doc_id[:8]}")
            score -= 0.2

    return GateResult(
        level="G3",
        passed=len(issues) == 0,
        score=max(0.0, score),
        issues=issues,
    )


def _log_gate_result(db: Session, doc_id: str, results: List[GateResult]):
    """记录门禁结果到 quality_gate_log 表。"""
    from app.models.concept import QualityGateLog

    for r in results:
        import json
        log = QualityGateLog(
            doc_id=doc_id,
            gate_level=r.level,
            passed=1 if r.passed else 0,
            score=r.score,
            issues=json.dumps(r.issues, ensure_ascii=False) if r.issues else None,
            checked_at=datetime.now(timezone.utc),
        )
        db.add(log)

    db.flush()  # 不 commit，由调用方决定

"""OKF Graph Traversal — KG 边 BFS 拉取关联 concept。

Phase B #5: query 时沿 KGTriple 边做 2-hop BFS 扩展，
将关联 doc 的 concept 注入 context。

V1 predicate 词表（阶段 B 仍保留，V2 在阶段 C 统一）：
  references, supersedes, defines, applies_to, cites, derives_from
"""

import logging
from typing import List, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.concept import Concept, KGTriple
from app.models.document import Document

logger = logging.getLogger(__name__)

# 遍历使用的 predicate 词表（V1 词表）
_TRAVERSE_PREDICATES = frozenset({
    "references", "supersedes", "defines", "applies_to", "cites", "derives_from",
})


def traverse_kg(
    db: Session,
    seed_doc_ids: List[str],
    max_depth: int = 2,
    max_nodes: int = 10,
) -> List[Dict]:
    """从 seed doc_id BFS，沿 KGTriple 边扩展。

    返回按 BFS 距离 + KGTriple.confidence 排序的关联节点信息。

    Args:
        db: 数据库 session
        seed_doc_ids: 起始文档 ID 列表
        max_depth: 最大 BFS 深度（默认 2）
        max_nodes: 最大返回节点数（默认 10）

    Returns:
        List of {doc_id, concept_id, predicate, depth, confidence}
        按 (depth ASC, confidence DESC) 排序
    """
    if not seed_doc_ids:
        return []

    visited: set = set(seed_doc_ids)
    frontier: List[str] = list(seed_doc_ids)
    results: List[Dict] = []

    for depth in range(max_depth):
        next_frontier: List[str] = []
        for did in frontier:
            # 查询与该 doc 相关的 KGTriple
            triples = db.query(KGTriple).filter(
                (KGTriple.subject_id == did) | (KGTriple.object_id == did),
                KGTriple.predicate.in_(_TRAVERSE_PREDICATES),
            ).order_by(KGTriple.confidence.desc()).limit(max_nodes).all()

            for t in triples:
                # 确定邻居方向
                if t.subject_id == did:
                    neighbor = t.object_id
                else:
                    neighbor = t.subject_id

                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_frontier.append(neighbor)

                # 查找 neighbor 对应的 concept（取第一个 active concept）
                concept = db.query(Concept).filter(
                    Concept.concept_id == neighbor,
                    Concept.status == "active",
                ).first()
                # 如果 neighbor 是 doc_id，尝试通过 doc_id 查找 concept
                if not concept:
                    concept = db.query(Concept).filter(
                        Concept.doc_id == neighbor,
                        Concept.status == "active",
                    ).first()

                results.append({
                    "doc_id": neighbor if concept is None else concept.doc_id,
                    "concept_id": neighbor if concept is None else concept.concept_id,
                    "predicate": t.predicate,
                    "depth": depth + 1,
                    "confidence": t.confidence or 1.0,
                })

                if len(results) >= max_nodes:
                    # Sort and return
                    results.sort(key=lambda x: (x["depth"], -x["confidence"]))
                    return results[:max_nodes]

        frontier = next_frontier
        if not frontier:
            break

    # Sort results by depth, then by confidence descending
    results.sort(key=lambda x: (x["depth"], -x["confidence"]))
    return results[:max_nodes]


def get_kg_context_for_query(
    db: Session,
    seed_doc_ids: List[str],
    max_depth: int = 2,
    max_nodes: int = 10,
    max_chars: int = 3000,
) -> Tuple[List[Dict], str]:
    """为查询生成 KG context（遍历结果 + 格式化文本）。

    Args:
        db: 数据库 session
        seed_doc_ids: 起始文档 ID
        max_depth: BFS 深度
        max_nodes: 最大节点数
        max_chars: 格式化文本最大字符数

    Returns:
        (kg_context_list, kg_context_text)
        kg_context_list: 结构化列表，供前端展示
        kg_context_text: 格式化文本，供 LLM prompt 注入
    """
    nodes = traverse_kg(db, seed_doc_ids, max_depth=max_depth, max_nodes=max_nodes)

    if not nodes:
        return [], ""

    # 构建格式化文本
    lines = []
    total_chars = 0
    kept_nodes = []

    for node in nodes:
        # 获取 concept 摘要
        concept = db.query(Concept).filter(
            Concept.concept_id == node["concept_id"],
            Concept.status == "active",
        ).first()

        if not concept:
            continue

        summary = concept.summary or ""
        if not summary and concept.content:
            summary = concept.content[:200]

        line = (
            f"[KG] {node['predicate']} (depth={node['depth']}, "
            f"conf={node['confidence']:.2f}): "
            f"{concept.title or node['concept_id']}"
        )
        if summary:
            line += f" — {summary}"

        if total_chars + len(line) > max_chars:
            break

        lines.append(line)
        total_chars += len(line)
        kept_nodes.append(node)

    context_text = "\n".join(lines) if lines else ""

    return kept_nodes, context_text

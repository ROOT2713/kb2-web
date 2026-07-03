"""OKF YAML Frontmatter - concept to OKF standard frontmatter view.

Phase B #4: support GET /api/concepts/get?format=frontmatter returning YAML frontmatter.
Also supports parse_frontmatter() for ingesting frontmatter from uploaded documents.
"""

import logging
from typing import Optional, List, Dict

import yaml

from sqlalchemy.orm import Session

from app.models.concept import Concept, KGTriple
from app.models.document import Document

logger = logging.getLogger(__name__)

_RELATED_PREDICATES = frozenset({
    "references", "supersedes", "defines", "applies_to", "cites", "derives_from",
})


def concept_to_frontmatter(db: Session, concept_id: str) -> Optional[str]:
    """Convert concept to OKF YAML frontmatter string."""
    concept = db.query(Concept).filter(Concept.concept_id == concept_id).first()
    if not concept:
        return None
    doc = db.query(Document).filter(Document.doc_id == concept.doc_id).first()
    lines: List[str] = ["---"]
    lines.append(f"concept_id: {_yaml_str(concept.concept_id)}")
    lines.append(f"doc_id: {_yaml_str(concept.doc_id)}")
    lines.append(f"title: {_yaml_str(concept.title or '')}")
    doc_type = doc.doc_type if doc and doc.doc_type else "generic"
    lines.append(f"type: {doc_type}")
    lines.append(f"status: {concept.status or 'active'}")
    conf = concept.confidence if concept.confidence is not None else 0.5
    lines.append(f"confidence: {conf:.3f}")
    if doc and doc.last_confirmed:
        lines.append(f"last_confirmed: {doc.last_confirmed.isoformat()}")
    elif doc and doc.verified_at:
        lines.append(f"last_confirmed: {doc.verified_at.isoformat()}")
    else:
        lines.append("last_confirmed: null")
    review = bool(doc.review_required) if doc and doc.review_required else False
    lines.append(f"review_required: {str(review).lower()}")
    lines.append("source_count: 1")
    lines.append("contradiction_count: 0")
    domain = doc.domain if doc and doc.domain else "unknown"
    subdomain = doc.subdomain if doc and doc.subdomain else "unknown"
    lines.append(f"domain: {_yaml_str(domain)}")
    lines.append(f"subdomain: {_yaml_str(subdomain)}")
    lines.append("sources:")
    lines.append(f"  - doc_id: {_yaml_str(concept.doc_id)}")
    related_edges = _get_related_edges(db, concept_id)
    lines.append("related:")
    if related_edges:
        for edge in related_edges:
            pred = edge["predicate"]
            neighbor = edge["neighbor_id"]
            neighbor_type = edge["neighbor_type"]
            lines.append(f"  - predicate: {_yaml_str(pred)}")
            lines.append(f"    {neighbor_type}: {_yaml_str(neighbor)}")
    else:
        lines.append("  []")
    lines.append("---")
    lines.append("")
    content = concept.content if isinstance(concept.content, str) else ""
    lines.append(content if content else "")
    return "\n".join(lines)


def _get_related_edges(db: Session, concept_id: str) -> List[Dict]:
    """Get related edges from KGTriple table."""
    triples = db.query(KGTriple).filter(
        (KGTriple.subject_id == concept_id) | (KGTriple.object_id == concept_id),
        KGTriple.predicate.in_(_RELATED_PREDICATES),
    ).order_by(KGTriple.confidence.desc()).limit(20).all()
    edges: List[Dict] = []
    for t in triples:
        if t.subject_id == concept_id:
            neighbor_id = t.object_id
            neighbor_type = t.object_type
        else:
            neighbor_id = t.subject_id
            neighbor_type = t.subject_type
        edges.append({
            "predicate": t.predicate,
            "neighbor_id": neighbor_id,
            "neighbor_type": neighbor_type,
        })
    return edges


def _yaml_str(val: str) -> str:
    """Safe YAML string escaping."""
    if not val:
        return '""'
    if any(ch in val for ch in (':', '#', '"', "'", '\n', '\r')) or val != val.strip():
        escaped = val.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return val


def parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from document text.

    Looks for a standard frontmatter block delimited by '---' lines
    at the start of the document. Returns an empty dict if:
    - No '---' delimiter found
    - Content before the first '---' is non-empty (not frontmatter)
    - YAML parsing fails for any reason

    Returns:
        dict with parsed frontmatter fields, or empty dict on failure.
    """
    if not text or not isinstance(text, str):
        return {}

    stripped = text.lstrip("\ufeff")  # strip BOM if present
    if not stripped.startswith("---"):
        return {}

    # Find the closing '---'
    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return {}

    yaml_block = stripped[3:end_idx].strip()
    if not yaml_block:
        return {}

    try:
        parsed = yaml.safe_load(yaml_block)
        if not isinstance(parsed, dict):
            return {}
        # Flatten any nested scalar values, filter out non-serializable
        result = {}
        for k, v in parsed.items():
            if isinstance(v, (str, int, float, bool)):
                result[str(k)] = v
            elif v is None:
                result[str(k)] = None
            elif isinstance(v, (list, dict)):
                # Keep simple lists/dicts but convert to JSON-compatible
                result[str(k)] = v
        return result
    except yaml.YAMLError:
        logger.warning("parse_frontmatter: YAML parse failed (len=%d)", len(yaml_block))
        return {}
    except Exception as e:
        logger.warning("parse_frontmatter: unexpected error: %s", e)
        return {}

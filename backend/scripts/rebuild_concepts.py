"""C3: Rebuild concepts + KG triples + summaries for reparse docs.

Usage: python -m app.scripts.rebuild_concepts <doc_id> <doc_title> <bank>
"""

import sys, logging
from sqlalchemy import text as sa_text

sys.path.insert(0, "/home/ubuntu/kb2-web/backend")

from app.models.database import SessionLocal
from app.models.document import Document, ParentChunk
from app.services.concept_gen import generate_concepts_for_doc, infer_doc_concept_id, infer_domain
from app.services.concept_summary import generate_summaries_batch
import importlib.util
_kg_spec = importlib.util.spec_from_file_location("kg_client", "/home/ubuntu/kb2-web/backend/scripts/kg_client.py")
_kg_mod = importlib.util.module_from_spec(_kg_spec)
_kg_spec.loader.exec_module(_kg_mod)
kg_index_document = _kg_mod.kg_index_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rebuild")

DOCS = [
    ("1e13f9e0-4bde-4126-8140-8798c835e0c2", "【实】JJF 1059.1-2012 测量不确定度评定与表示", "standards"),
    ("51d536d9-2c66-48b5-9f88-dd55b1b79137", "【安】GB∕T 2828.1-2012 计数抽样检验程序", "standards"),
]


def rebuild(doc_id, doc_title, bank):
    db = SessionLocal()
    try:
        # 1) Check parent_chunks
        rows = db.execute(
            sa_text("SELECT parent_idx, parent_text FROM parent_chunks WHERE doc_id=:did ORDER BY parent_idx"),
            {"did": doc_id},
        ).fetchall()
        if not rows:
            logger.error("No parent_chunks for %s", doc_id[:8])
            return

        parent_map = [{"parent_index": idx, "parent": text} for idx, text in rows]
        full_text = "\n\n".join(text for _, text in rows)
        logger.info("%s: %d parent_chunks, %d chars", doc_id[:8], len(parent_map), len(full_text))

        # 2) Update document metadata
        doc_type = "gb_standard"
        doc_concept_id = infer_doc_concept_id(title=doc_title, bank=bank, doc_type=doc_type, text=full_text[:2000])
        domain = infer_domain(bank, doc_type)

        db.execute(
            sa_text(
                "UPDATE documents SET doc_type=:dt, concept_id=:cid, domain=:domain, "
                "chunk_count=:cc, coverage_pct=:cp WHERE doc_id=:did"
            ),
            {"dt": doc_type, "cid": doc_concept_id, "domain": domain, "cc": len(parent_map),
             "cp": 100.0, "did": doc_id},
        )
        db.commit()

        # 3) Generate concepts
        concept_count = generate_concepts_for_doc(
            db, doc_id, doc_concept_id, parent_map,
            doc_type=doc_type, confidence=0.85,
        )
        logger.info("%s: %d concepts generated", doc_id[:8], concept_count)

        # 4) Generate KG triples
        try:
            kg_result = kg_index_document(doc_id, doc_title, full_text, bank)
            logger.info("%s: KG triple count: %s", doc_id[:8], kg_result.get("count", 0))
        except Exception as e:
            logger.warning("KG triple gen failed (non-critical): %s", e)

        # 5) Backfill summaries
        import asyncio
        summary_count = asyncio.run(generate_summaries_batch(db, doc_id, limit=100))
        logger.info("%s: %d summaries generated", doc_id[:8], summary_count)

        db.commit()
        logger.info("DONE: %s", doc_id[:8])

    except Exception as e:
        logger.error("Rebuild failed for %s: %s", doc_id[:8], e, exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    for did, title, bank in DOCS:
        rebuild(did, title, bank)
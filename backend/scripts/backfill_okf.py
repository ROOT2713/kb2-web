#!/usr/bin/env python3
"""P0-7: 存量回填 concept_id + concepts

为所有旧文档生成 doc 级 concept_id，并基于 parent_chunks 生成 section-level concepts。
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models.database import SessionLocal
from app.models.document import Document, ParentChunk
from app.models.concept import Concept
from app.services.concept_gen import infer_doc_concept_id, generate_concepts_for_doc

def backfill_concept_ids(session):
    """Step 1: 为所有文档生成 concept_id"""
    docs = session.query(Document).filter(
        (Document.concept_id == None) | (Document.concept_id == '')
    ).all()
    
    print(f"找到 {len(docs)} 个文档需要回填 concept_id")
    
    updated = 0
    for doc in docs:
        concept_id = infer_doc_concept_id(
            title=doc.title or "",
            bank=doc.bank or "general",
            doc_type=doc.doc_type or "generic",
            text=""  # 不读取全文，仅标题+元数据
        )
        if concept_id:
            doc.concept_id = concept_id
            # 同时填充 domain 和 subdomain
            parts = concept_id.split("/")
            doc.domain = parts[0] if parts else None
            doc.subdomain = parts[1] if len(parts) > 2 else None
            updated += 1
    
    session.commit()
    print(f"✅ 更新了 {updated} 个文档的 concept_id")
    
    # 统计
    from collections import Counter
    domain_dist = Counter(d.domain for d in docs if d.domain)
    print("\n按 domain 分布:")
    for domain, cnt in domain_dist.most_common():
        print(f"  {domain}: {cnt}")

def backfill_concepts(session):
    """Step 2: 为每个文档生成 section-level concepts"""
    docs = session.query(Document).filter(
        Document.concept_id != None,
        Document.concept_id != ''
    ).all()
    
    print(f"\n找到 {len(docs)} 个文档有 concept_id，开始生成 concepts")
    
    total_concepts = 0
    processed = 0
    
    for doc in docs:
        # 检查是否已有 concepts
        existing = session.query(Concept).filter(Concept.doc_id == doc.doc_id).count()
        if existing > 0:
            print(f"  跳过 {doc.doc_id[:8]}.. (已有 {existing} 个 concept)")
            continue
        
        # 获取 parent_chunks
        chunks = session.query(ParentChunk).filter(
            ParentChunk.doc_id == doc.doc_id
        ).order_by(ParentChunk.parent_idx).all()
        
        if not chunks:
            print(f"  跳过 {doc.doc_id[:8]}.. (无 parent_chunks)")
            continue
        
        parent_chunks = [
            {"parent_index": c.parent_idx, "parent": c.parent_text}
            for c in chunks
        ]
        
        count = generate_concepts_for_doc(
            db=session,
            doc_id=doc.doc_id,
            concept_id=doc.concept_id,
            parent_chunks=parent_chunks,
            doc_type=doc.doc_type or "generic",
            confidence=0.5,
        )
        
        total_concepts += count
        processed += 1
        
        if processed % 20 == 0:
            print(f"  进度: {processed}/{len(docs)} 文档, {total_concepts} concepts")
    
    session.commit()
    print(f"\n✅ 生成了 {total_concepts} 个 concepts，处理了 {processed} 个文档")

if __name__ == "__main__":
    start = time.time()
    
    print("=" * 60)
    print("P0-7: 存量回填 concept_id + concepts")
    print("=" * 60)
    
    session = SessionLocal()
    try:
        backfill_concept_ids(session)
        backfill_concepts(session)
    finally:
        session.close()
    
    elapsed = time.time() - start
    print(f"\n⏱️ 耗时: {elapsed:.1f}s")

"""kb2-web pgvector vs Hindsight recall comparison test.
用法: python3 tools/compare_recall.py [pgvector|hindsight]
"""
import asyncio, json, os, sys, time
from pathlib import Path

# ── 测试查询集（覆盖不同领域） ──
TEST_QUERIES = [
    # 项目验收/概算
    "广州市政务信息化项目验收管理细则",
    "电子政务工程造价指导书 概算编制",
    # 等保测评
    "等保三级 测评要求",
    "网络安全等级保护基本要求 对应条款",
    # 技术标准
    "GB 50348 安全防范工程技术标准",
    "数据中心基础设施施工及验收标准",
    # 信息安全
    "系统与软件质量要求 GB/T 25000",
    "消防联动控制系统 GB 16806",
]

async def test_recall(mode: str):
    """Run the 8 queries against the given backend mode."""
    # Set the vector_backend env
    os.environ["VECTOR_BACKEND"] = mode
    
    # Import after setting env
    from app.models.database import SessionLocal
    from app.repositories.vector_repo import get_vector_store
    
    store = get_vector_store()
    
    results = []
    for q in TEST_QUERIES:
        t0 = time.time()
        try:
            docs = await store.query(query_text=q, bank="kb_standard", top_k=5)
            latency = time.time() - t0
            results.append({
                "query": q,
                "latency_ms": round(latency * 1000),
                "count": len(docs),
                "texts": [d["text"][:100] for d in docs[:3]],
                "scores": [round(d.get("score", 0), 4) for d in docs[:3]],
            })
        except Exception as e:
            results.append({
                "query": q,
                "error": str(e),
            })
    
    return results

def print_comparison(pg_res, hs_res):
    print(f"\n{'='*80}")
    print(f"{'PGVECTOR vs HINDSIGHT RECALL 对比':^80}")
    print(f"{'='*80}")
    
    for i, q in enumerate(TEST_QUERIES):
        pg = pg_res[i] if i < len(pg_res) else {}
        hs = hs_res[i] if i < len(hs_res) else {}
        
        pg_count = pg.get("count", "ERR")
        hs_count = hs.get("count", "ERR")
        pg_lat = pg.get("latency_ms", "—")
        hs_lat = hs.get("latency_ms", "—")
        
        pg_scores = pg.get("scores", [])
        hs_scores = hs.get("scores", [])
        
        print(f"\n--- Q{i+1}: {q[:50]}...")
        
        # Badge
        if isinstance(pg_count, int) and isinstance(hs_count, int):
            if pg_count >= hs_count:
                print(f"  ✅ pgvector: {pg_count} results ({pg_lat}ms)  |  Hindsight: {hs_count} results ({hs_lat}ms)")
            else:
                print(f"  ⚠️ pgvector: {pg_count} results ({pg_lat}ms)  |  Hindsight: {hs_count} results ({hs_lat}ms)")
        else:
            print(f"  pgvector: {pg_count} ({pg_lat}ms)  |  Hindsight: {hs_count} ({hs_lat}ms)")
        
        if pg_scores:
            print(f"  pgvector top scores: {pg_scores}")
        if hs_scores:
            print(f"  Hindsight top scores: {hs_scores}")
        
        if "error" in pg:
            print(f"  pgvector ERROR: {pg['error']}")
        if "error" in hs:
            print(f"  Hindsight ERROR: {hs['error']}")
    
    # Summary
    print(f"\n{'─'*80}")
    pg_total = sum(1 for r in pg_res if isinstance(r.get("count"), int))
    hs_total = sum(1 for r in hs_res if isinstance(r.get("count"), int))
    print(f"pgvector: {pg_total}/{len(TEST_QUERIES)} 成功,  Hindsight: {hs_total}/{len(TEST_QUERIES)} 成功")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    if mode in ("pgvector", "all"):
        print("=== 测试 pgvector ===")
        os.environ["VECTOR_BACKEND"] = "pgvector"
        os.environ["EMBEDDING_URL"] = "https://open.bigmodel.cn/api/paas/v4/embeddings"
        os.environ["EMBEDDING_MODEL"] = "embedding-2"
        os.environ["EMBEDDING_API_KEY"] = "66de3c92ba1e435781d9fd8cfc5f6eb1.nxw8tsvAAQu0VVFr"
        pg_results = asyncio.run(test_recall("pgvector"))
    else:
        pg_results = None
    
    if mode in ("hindsight", "all"):
        print("=== 测试 Hindsight ===")
        os.environ["VECTOR_BACKEND"] = "hindsight"
        hs_results = asyncio.run(test_recall("hindsight"))
    else:
        hs_results = None
    
    if pg_results and hs_results:
        print_comparison(pg_results, hs_results)
    elif pg_results:
        print(json.dumps(pg_results, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(hs_results, indent=2, ensure_ascii=False))

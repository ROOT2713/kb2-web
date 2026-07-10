"""创建 pgvector 向量表 + HNSW 索引。"""
import asyncio
import asyncpg


async def create():
    conn = await asyncpg.connect("postgresql://hindsight:hindsight123@localhost:5432/hindsight")
    # Enable pgvector extension
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Create the vector_chunks table
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS vector_chunks (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id      TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            bank        TEXT NOT NULL,
            content     TEXT NOT NULL,
            metadata    JSONB NOT NULL DEFAULT '{}',
            embedding   vector(1024),
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    # B-tree indexes
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_vc_bank ON vector_chunks (bank)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_vc_doc_id ON vector_chunks (doc_id)")
    # HNSW index (pgvector >= 0.5.0)
    try:
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vc_embedding ON vector_chunks "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 24, ef_construction = 200)"
        )
        print("HNSW index created successfully")
    except Exception as e:
        print(f"HNSW index creation failed (fallback to IVFFlat): {e}")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vc_embedding ON vector_chunks "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        print("IVFFlat index created as fallback")
    await conn.close()
    print("Tables created successfully")


asyncio.run(create())

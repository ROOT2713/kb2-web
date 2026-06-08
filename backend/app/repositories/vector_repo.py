"""Vector store abstraction — interface for Hindsight / future backends."""

from typing import List, Dict, Optional, Protocol


class VectorStore(Protocol):
    """Abstract interface for vector storage backends."""

    async def upsert(self, doc_id: str, chunks: List[Dict], bank: str) -> int:
        """Insert/update document chunks. Returns chunk count."""
        ...

    async def query(self, embedding: List[float], bank: str, top_k: int = 20) -> List[Dict]:
        """Semantic vector search."""
        ...

    async def delete(self, doc_id: str, bank: str) -> bool:
        """Delete all chunks of a document."""
        ...

    async def list_documents(self, bank: str) -> List[Dict]:
        """List all documents in a bank."""
        ...


class HindsightStore:
    """Hindsight HTTP API adapter."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    async def upsert(self, doc_id: str, chunks: List[Dict], bank: str) -> int:
        # TODO: Port from kb-web server.py hindsight_request()
        raise NotImplementedError

    async def query(self, embedding: List[float], bank: str, top_k: int = 20) -> List[Dict]:
        raise NotImplementedError

    async def delete(self, doc_id: str, bank: str) -> bool:
        raise NotImplementedError

    async def list_documents(self, bank: str) -> List[Dict]:
        raise NotImplementedError

"""Embedding utilities — get query/document embeddings via API."""

from typing import List

from app.config import settings


async def get_embedding(text: str) -> List[float]:
    """Get embedding vector for a text via embedding API."""
    # TODO: Port get_query_embedding() from kb-web server.py
    raise NotImplementedError

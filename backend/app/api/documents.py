"""Document management endpoints — list, get, delete, reparse."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("")
async def list_documents(bank: str = "all"):
    """List all documents with metadata."""
    raise HTTPException(501, "Not implemented")


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """Get single document metadata."""
    raise HTTPException(501, "Not implemented")


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """Delete document from index + Hindsight + cache."""
    raise HTTPException(501, "Not implemented")


@router.post("/{doc_id}/reparse")
async def reparse_document(doc_id: str):
    """Re-parse and re-index an existing document."""
    raise HTTPException(501, "Not implemented")

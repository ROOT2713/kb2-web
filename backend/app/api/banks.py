"""Bank management endpoints — CRUD for knowledge bases."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("")
async def list_banks():
    """List all knowledge bases."""
    raise HTTPException(501, "Not implemented")


@router.post("")
async def create_bank(name: str, display_name: str = ""):
    """Create a new knowledge base."""
    raise HTTPException(501, "Not implemented")


@router.delete("/{bank_id}")
async def delete_bank(bank_id: str):
    """Delete a knowledge base and all its documents."""
    raise HTTPException(501, "Not implemented")

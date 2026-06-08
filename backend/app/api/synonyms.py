"""Synonym management endpoints."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("")
async def list_synonyms():
    """List all synonym mappings."""
    raise HTTPException(501, "Not implemented")


@router.post("")
async def add_synonym(word: str, synonyms: list[str]):
    """Add synonym mapping."""
    raise HTTPException(501, "Not implemented")


@router.delete("/{word}")
async def delete_synonym(word: str):
    """Delete synonym mapping."""
    raise HTTPException(501, "Not implemented")

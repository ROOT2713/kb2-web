"""Upload endpoint — document upload, parsing, chunking, indexing."""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

router = APIRouter()


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    bank: str = Form("general"),
    source: str = Form("manual"),
):
    """Upload a document: parse → chunk → embed → index → cache invalidate."""
    # TODO: Port from kb-web server.py upload() (L2675-L3039)
    raise HTTPException(501, "Not implemented — pending Phase 2 migration")

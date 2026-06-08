"""Document parsing service — PDF/Word/Excel/OCR pipeline.

Ported from: kb-web server.py parse_document() L815-L1034, mineru_parse_pdf() L654-L777,
             ocr_pdf() L590-L652, docx_to_pdf_via_libreoffice() L779-L809
"""

from pathlib import Path
from typing import Optional

from app.config import settings


async def parse_document(filename: str, content: bytes) -> str:
    """
    Parse document to plain text. Dispatch by file extension:
    - .pdf  → MinerU API → pypdf → OCR (fallback chain)
    - .docx → LibreOffice → pypdf
    - .xlsx → openpyxl structured extraction
    - .txt  → direct read
    """
    # TODO: Port from kb-web server.py parse_document()
    raise NotImplementedError


async def mineru_parse_pdf(filename: str, content: bytes) -> str:
    """Parse PDF via MinerU API (preferred)."""
    # TODO: Port from kb-web server.py mineru_parse_pdf()
    raise NotImplementedError


def ocr_pdf(pdf_bytes: bytes) -> str:
    """OCR fallback for scanned PDFs using Tesseract."""
    # TODO: Port from kb-web server.py ocr_pdf()
    raise NotImplementedError

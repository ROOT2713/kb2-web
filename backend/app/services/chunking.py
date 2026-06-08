"""Text chunking strategies — heading-based, parent-child, excel-row.

Ported from: kb-web server.py L1890-L2598
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Chunk:
    text: str
    index: int
    heading: str = ""
    parent_idx: Optional[int] = None
    metadata: dict = None


class ChunkingStrategy:
    """Base class for chunking strategies."""

    def chunk(self, text: str, filename: str = "", **kwargs) -> List[Chunk]:
        raise NotImplementedError


class HeadingChunking(ChunkingStrategy):
    """Split by document headings (## / ### / 一、二、三)."""
    # TODO: Port heading_chunk() logic
    pass


class ParentChildChunking(ChunkingStrategy):
    """Parent-child chunking with overlap for long sections."""
    # TODO: Port parent_child_chunk() logic
    pass


class ExcelRowChunking(ChunkingStrategy):
    """Excel-specific: each row = one chunk with column headers as context."""
    # TODO: Port excel_row_chunk() logic
    pass


def select_strategy(filename: str, text: str) -> ChunkingStrategy:
    """Auto-select the best chunking strategy based on document type."""
    if filename.endswith((".xlsx", ".xls")):
        return ExcelRowChunking()
    # Default: heading-based with parent-child fallback
    return HeadingChunking()

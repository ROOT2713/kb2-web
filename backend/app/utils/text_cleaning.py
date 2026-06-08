"""Text cleaning pipeline.

Ported from: kb-web server.py clean_pipeline() L1100-L1112, clean_watermarks() L1035-L1058,
             clean_page_artifacts() L1059-L1065, clean_html_residuals() L1066-L1072,
             clean_encoding_errors() L1073-L1079, normalize_whitespace() L1080-L1094,
             clean_transcript_errors() L1095-L1099
"""

import re


def clean_watermarks(text: str) -> str:
    """Remove website watermarks (e.g. www.bzfxw.com)."""
    # TODO: Port watermark regex patterns
    text = re.sub(r"www\.[a-zA-Z0-9]+\.com", "", text)
    return text


def clean_page_artifacts(text: str) -> str:
    """Remove page numbers, headers/footers."""
    text = re.sub(r"第\s*\d+\s*页.*?\n", "", text)
    return text


def clean_html_residuals(text: str) -> str:
    """Remove HTML tags and entities."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return text


def clean_encoding_errors(text: str) -> str:
    """Fix common encoding issues."""
    replacements = {
        "\ufffd": "",  # replacement character
        "\xa0": " ",   # non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace, strip lines."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_pipeline(text: str, source_hint: str = "") -> str:
    """Run full cleaning pipeline."""
    text = clean_encoding_errors(text)
    text = clean_html_residuals(text)
    text = clean_watermarks(text)
    text = clean_page_artifacts(text)
    text = normalize_whitespace(text)
    return text

"""PDF -> list of page texts (index 0 = page 1)."""
from pathlib import Path

from pypdf import PdfReader


def read_pages(path: Path) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(path).pages]

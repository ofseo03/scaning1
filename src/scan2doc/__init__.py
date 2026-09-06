"""scan2doc — 사진·스크린샷·PDF를 Word와 한글 문서로 바꾸는 도구."""

from __future__ import annotations

__version__ = "0.1.0"

from .config import ConvertOptions, PreprocessOptions
from .errors import (
    DependencyError,
    InputError,
    OcrError,
    Scan2DocError,
    WriterError,
)
from .model import BBox, Block, BlockKind, Document, Line, Page, Word

__all__ = [
    "BBox",
    "Block",
    "BlockKind",
    "ConvertOptions",
    "DependencyError",
    "Document",
    "InputError",
    "Line",
    "OcrError",
    "Page",
    "PreprocessOptions",
    "Scan2DocError",
    "Word",
    "WriterError",
    "__version__",
    "convert",
]


def convert(inputs, options=None, progress=None):
    """편의 함수: scan2doc.convert(["a.jpg"], ConvertOptions(...))"""
    from .config import ConvertOptions as _Options
    from .pipeline import convert as _convert

    return _convert(inputs, options or _Options(), progress=progress)

"""출력 형식 레지스트리."""

from __future__ import annotations

from ..errors import Scan2DocError
from .base import DocumentWriter
from .docx_writer import DocxWriter
from .hwpml_writer import HwpmlWriter
from .hwpx_writer import HwpxWriter
from .text_writer import MarkdownWriter, TextWriter

_WRITERS: dict[str, type[DocumentWriter]] = {}


def register(writer_cls: type[DocumentWriter]) -> type[DocumentWriter]:
    _WRITERS[writer_cls.name] = writer_cls
    return writer_cls


def get_writer(name: str) -> DocumentWriter:
    key = name.lower().lstrip(".")
    # 'hwp'는 사용자가 가장 자주 쓰는 이름이므로 표준 hwpx로 안내한다.
    if key == "hwp":
        key = "hwpx"
    try:
        return _WRITERS[key]()
    except KeyError:
        raise Scan2DocError(
            f"알 수 없는 출력 형식입니다: {name} (사용 가능: {', '.join(available_writers())})"
        ) from None


def available_writers() -> list[str]:
    return sorted(_WRITERS)


def describe_writers() -> list[tuple[str, str, str]]:
    return [
        (cls.name, cls.extension, cls.description)
        for cls in sorted(_WRITERS.values(), key=lambda c: c.name)
    ]


for _cls in (DocxWriter, HwpxWriter, HwpmlWriter, TextWriter, MarkdownWriter):
    register(_cls)

__all__ = [
    "DocumentWriter",
    "DocxWriter",
    "HwpmlWriter",
    "HwpxWriter",
    "MarkdownWriter",
    "TextWriter",
    "available_writers",
    "describe_writers",
    "get_writer",
    "register",
]

"""문서 작성기 공통 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..config import ConvertOptions
from ..model import Document


class DocumentWriter(ABC):
    """중간 문서 모델을 특정 파일 형식으로 저장한다."""

    name: str = "base"
    extension: str = ""
    description: str = ""

    @abstractmethod
    def write(self, document: Document, path: Path, options: ConvertOptions) -> Path:
        """document를 path에 저장하고 실제 저장된 경로를 돌려준다."""

    def target_path(self, base: Path) -> Path:
        """확장자를 이 형식에 맞게 바꾼 경로."""
        return base.with_suffix(self.extension)


def sanitize_xml_text(text: str) -> str:
    """XML 1.0에서 허용하지 않는 제어문자를 제거한다."""
    return "".join(
        ch for ch in text
        if ch in "\t\n\r" or 0x20 <= ord(ch) <= 0xD7FF or 0xE000 <= ord(ch) <= 0xFFFD
    )

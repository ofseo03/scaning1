"""OCR 엔진 공통 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PIL import Image

from ..config import ConvertOptions
from ..layout import WordRecord


@dataclass
class OcrResult:
    """엔진이 한 페이지를 인식한 결과."""

    records: list[WordRecord] = field(default_factory=list)
    rotation: int = 0
    """엔진이 감지해 적용한 회전 각도(0/90/180/270)."""

    engine: str = ""
    psm: int = 0
    """이 결과를 얻는 데 쓴 페이지 분할 모드."""

    @property
    def confidence(self) -> float:
        scored = [r.confidence for r in self.records if r.confidence >= 0]
        return sum(scored) / len(scored) if scored else -1.0


class OcrEngine(ABC):
    """OCR 엔진 어댑터.

    새 엔진을 붙이려면 이 클래스를 상속하고 register()로 등록하면 된다.
    """

    name: str = "base"
    description: str = ""

    @abstractmethod
    def check(self) -> None:
        """실행 가능한 상태인지 확인한다. 아니면 DependencyError를 던진다."""

    @abstractmethod
    def recognize(self, image: Image.Image, options: ConvertOptions) -> OcrResult:
        """이미지 한 장을 인식한다."""

    def languages(self) -> list[str]:
        """설치된 언어 데이터 목록(알 수 없으면 빈 목록)."""
        return []

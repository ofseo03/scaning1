"""OCR 엔진 레지스트리."""

from __future__ import annotations

from ..errors import Scan2DocError
from .base import OcrEngine, OcrResult
from .tesseract import TesseractEngine

_ENGINES: dict[str, type[OcrEngine]] = {}


def register(engine_cls: type[OcrEngine]) -> type[OcrEngine]:
    """엔진 클래스를 이름으로 등록한다(데코레이터로도 사용 가능)."""
    _ENGINES[engine_cls.name] = engine_cls
    return engine_cls


def get_engine(name: str) -> OcrEngine:
    try:
        return _ENGINES[name]()
    except KeyError:
        raise Scan2DocError(
            f"알 수 없는 OCR 엔진입니다: {name} (사용 가능: {', '.join(available_engines())})"
        ) from None


def available_engines() -> list[str]:
    return sorted(_ENGINES)


register(TesseractEngine)

__all__ = [
    "OcrEngine",
    "OcrResult",
    "TesseractEngine",
    "available_engines",
    "get_engine",
    "register",
]

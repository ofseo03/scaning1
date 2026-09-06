"""scan2doc 예외 정의."""

from __future__ import annotations


class Scan2DocError(Exception):
    """이 패키지가 발생시키는 모든 오류의 기반 클래스."""


class DependencyError(Scan2DocError):
    """필요한 외부 프로그램이나 파이썬 패키지가 없을 때."""


class InputError(Scan2DocError):
    """입력 파일을 읽을 수 없거나 지원하지 않는 형식일 때."""


class OcrError(Scan2DocError):
    """OCR 엔진 실행이 실패했을 때."""


class WriterError(Scan2DocError):
    """문서 작성에 실패했을 때."""

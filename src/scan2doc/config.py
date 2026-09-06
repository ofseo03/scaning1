"""변환 옵션 정의."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

#: 입력으로 받아들이는 이미지 확장자
IMAGE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif",
    ".tif", ".tiff", ".webp", ".ppm", ".pgm",
}

#: 입력으로 받아들이는 문서 확장자
DOC_SUFFIXES = {".pdf"}

SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | DOC_SUFFIXES


@dataclass
class PreprocessOptions:
    """OCR 전에 이미지에 적용할 보정."""

    enabled: bool = True
    grayscale: bool = True
    denoise: bool = False
    binarize: bool = False
    deskew: bool = True
    auto_rotate: bool = True
    """Tesseract OSD로 90/180/270도 회전을 감지해 바로 세운다."""

    max_skew_deg: float = 15.0
    upscale_min_width: int = 1000
    """가로 폭이 이보다 작으면 확대해서 인식률을 높인다."""

    upscale_target_width: int = 1800

    def disabled_copy(self) -> "PreprocessOptions":
        return replace(self, enabled=False)


@dataclass
class ConvertOptions:
    """한 번의 변환 실행에 대한 모든 설정."""

    # 출력
    output: Path | None = None
    formats: list[str] = field(default_factory=lambda: ["docx", "hwpx"])
    merge: bool = False
    """여러 입력 파일을 문서 하나로 합칠지 여부."""

    overwrite: bool = False

    # OCR
    engine: str = "tesseract"
    language: str = "kor+eng"
    psm: int | str = "auto"
    """페이지 분할 모드. "auto"면 4 → 3 순으로 시도해 더 좋은 쪽을 쓴다."""

    oem: int = 3
    ocr_timeout: int = 180
    """한 쪽당 OCR 제한 시간(초)."""

    tesseract_cmd: str | None = None
    min_confidence: float = 0.0
    """이 신뢰도 미만의 낱말은 버린다(0이면 버리지 않음)."""

    # 입력 처리
    dpi: int = 300
    """PDF 페이지를 이미지로 렌더링할 해상도."""

    pdf_text: str = "auto"
    """auto | always | never — PDF 내장 텍스트 레이어 사용 정책."""

    pages: str = ""
    """페이지 범위 지정(예: '1-3,7'). 비우면 전체."""

    recursive: bool = False

    # 레이아웃 재구성
    detect_headings: bool = True
    detect_lists: bool = True
    keep_line_breaks: bool = False
    """참이면 줄바꿈을 그대로 보존한다(문단으로 합치지 않음)."""

    page_break: bool = True
    """페이지 사이에 쪽 나눔을 넣을지."""

    embed_image: bool = False
    """각 페이지의 원본 이미지를 문서에 함께 넣는다."""

    # 문서 서식
    title: str = ""
    font_korean: str = "맑은 고딕"
    font_latin: str = "맑은 고딕"
    font_size: float = 11.0
    line_spacing: float = 1.6

    # HWP
    hwp_format: str = "hwpx"
    """hwpx(OWPML 표준, 한/글 2014 이상) 또는 hwpml(구버전 XML)."""

    # 기타
    preprocess: PreprocessOptions = field(default_factory=PreprocessOptions)
    report: Path | None = None
    quiet: bool = False
    verbose: bool = False


def parse_page_range(spec: str, total: int) -> list[int]:
    """'1-3,7,10-' 형식의 페이지 지정을 1부터 시작하는 번호 목록으로 바꾼다."""
    if not spec.strip():
        return list(range(1, total + 1))

    selected: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_s, _, end_s = chunk.partition("-")
            start = int(start_s) if start_s.strip() else 1
            end = int(end_s) if end_s.strip() else total
        else:
            start = end = int(chunk)
        if start > end:
            start, end = end, start
        selected.update(range(max(1, start), min(total, end) + 1))
    return sorted(selected)

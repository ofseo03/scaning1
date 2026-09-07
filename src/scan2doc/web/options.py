"""브라우저가 보낸 설정값을 ConvertOptions로 옮긴다.

웹에서 오는 값은 믿을 수 없으므로 **허용 목록**만 받는다. 저장 경로(`output`),
리포트 경로(`report`), tesseract 실행 파일 경로(`tesseract_cmd`)처럼 서버의
파일 시스템을 건드리는 항목은 아예 받지 않는다. 그런 값은 서버가 정한다.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from ..config import SUPPORTED_SUFFIXES, ConvertOptions, PreprocessOptions
from ..errors import InputError, Scan2DocError
from ..writers import available_writers

#: 웹에서 고를 수 있는 출력 형식 (hwp는 hwp_format 설정을 따른다)
WEB_FORMATS = ("docx", "hwpx", "hwpml", "txt", "md")

#: 한 쪽당 OCR 제한 시간의 상한. 브라우저가 무한정 붙잡아 두지 못하게 한다.
MAX_OCR_TIMEOUT = 600

#: PDF 렌더링 해상도 범위
DPI_RANGE = (72, 600)

_SAFE_NAME = re.compile(r"[^\w가-힣.\- ()\[\]]+", re.UNICODE)


def parse_options(raw: dict[str, Any] | None) -> ConvertOptions:
    """요청 본문(JSON 객체)을 ConvertOptions로 바꾼다."""
    data = dict(raw or {})
    options = ConvertOptions()

    options.formats = _formats(data.get("formats"))
    options.hwp_format = _choice(data, "hwp_format", ("hwpx", "hwpml"), "hwpx")
    options.merge = _bool(data, "merge", False)
    options.title = _text(data.get("title"), limit=200)

    options.language = _language(data.get("language"))
    options.psm = _psm(data.get("psm"))
    options.oem = _int(data, "oem", 3, 0, 3)
    options.ocr_timeout = _int(data, "ocr_timeout", 180, 5, MAX_OCR_TIMEOUT)
    options.min_confidence = _float(data, "min_confidence", 0.0, 0.0, 100.0)

    options.dpi = _int(data, "dpi", 300, *DPI_RANGE)
    options.pages = _pages(data.get("pages"))
    options.pdf_text = _choice(data, "pdf_text", ("auto", "always", "never"), "auto")
    options.all_frames = _bool(data, "all_frames", False)

    options.detect_headings = _bool(data, "detect_headings", True)
    options.detect_lists = _bool(data, "detect_lists", True)
    options.keep_line_breaks = _bool(data, "keep_line_breaks", False)
    options.page_break = _bool(data, "page_break", True)
    options.embed_image = _bool(data, "embed_image", False)

    options.font_korean = _text(data.get("font_korean"), limit=60) or "맑은 고딕"
    options.font_latin = _text(data.get("font_latin"), limit=60) or options.font_korean
    options.font_size = _float(data, "font_size", 11.0, 6.0, 40.0)
    options.line_spacing = _float(data, "line_spacing", 1.6, 1.0, 3.0)

    options.preprocess = _preprocess(data.get("preprocess"))

    # 웹에서는 결과를 작업 폴더에만 쓴다. 덮어쓸 파일 자체가 없으므로 항상 참.
    options.overwrite = True
    options.quiet = True
    return options


def safe_filename(name: str) -> str:
    """올라온 파일 이름에서 경로와 위험한 문자를 걷어낸다.

    브라우저(특히 옛 IE나 일부 모바일)는 전체 경로를 보내기도 하고, 악의적인
    클라이언트는 `../../etc/passwd` 같은 이름을 보낼 수도 있다. 이름만 남긴다.
    """
    name = unicodedata.normalize("NFC", (name or "").strip())
    # 윈도우 경로와 POSIX 경로 양쪽에서 마지막 조각만 취한다.
    name = PureWindowsPath(PurePosixPath(name).name).name
    name = _SAFE_NAME.sub("_", name).strip(" .")
    return name or "upload"


def check_supported(name: str) -> str:
    """지원하는 확장자인지 확인하고 정리된 이름을 돌려준다."""
    cleaned = safe_filename(name)
    suffix = Path(cleaned).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        allowed = ", ".join(sorted(s.lstrip(".") for s in SUPPORTED_SUFFIXES))
        raise InputError(f"지원하지 않는 형식입니다: {cleaned} (가능: {allowed})")
    return cleaned


# --- 항목별 해석 ----------------------------------------------------------

def _formats(value: Any) -> list[str]:
    if value is None or value == "":
        return ["docx", "hwpx"]
    if isinstance(value, str):
        items = [v.strip().lower() for v in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(v).strip().lower() for v in value]
    else:
        raise Scan2DocError("출력 형식(formats)은 목록이나 쉼표로 구분한 문자열이어야 합니다.")

    known = set(available_writers()) | {"hwp"}
    picked: list[str] = []
    for item in items:
        if not item:
            continue
        if item not in known:
            raise Scan2DocError(
                f"알 수 없는 출력 형식입니다: {item} (가능: {', '.join(WEB_FORMATS)})"
            )
        if item not in picked:
            picked.append(item)
    if not picked:
        raise Scan2DocError("출력 형식을 하나 이상 골라 주세요.")
    return picked


def _language(value: Any) -> str:
    text = _text(value, limit=80) or "kor+eng"
    # Tesseract 언어 코드는 영문자·숫자와 +, _ 만 쓴다. 명령줄로 넘어가는 값이므로
    # 형식을 벗어난 입력은 여기서 막는다.
    if not re.fullmatch(r"[A-Za-z0-9_+\-]+", text):
        raise Scan2DocError(f"언어 코드 형식이 잘못됐습니다: {text} (예: kor, eng, kor+eng)")
    return text


def _psm(value: Any) -> int | str:
    if value is None or value == "" or str(value).lower() == "auto":
        return "auto"
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise Scan2DocError(f"psm 값이 잘못됐습니다: {value} (auto 또는 0~13)") from None
    if not 0 <= number <= 13:
        raise Scan2DocError(f"psm은 0~13 사이여야 합니다: {number}")
    return number


def _pages(value: Any) -> str:
    text = _text(value, limit=200)
    if text and not re.fullmatch(r"[0-9,\-\s]*", text):
        raise Scan2DocError(f"쪽 범위 형식이 잘못됐습니다: {text} (예: 1-3,7)")
    return text


def _preprocess(value: Any) -> PreprocessOptions:
    data = value if isinstance(value, dict) else {}
    return PreprocessOptions(
        enabled=_bool(data, "enabled", True),
        grayscale=_bool(data, "grayscale", True),
        denoise=_bool(data, "denoise", False),
        binarize=_bool(data, "binarize", False),
        deskew=_bool(data, "deskew", True),
        auto_rotate=_bool(data, "auto_rotate", True),
    )


# --- 자잘한 변환기 --------------------------------------------------------

_TRUE = {"1", "true", "yes", "on", "y", "참"}
_FALSE = {"0", "false", "no", "off", "n", "거짓", ""}


def _bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise Scan2DocError(f"{key} 값이 잘못됐습니다: {value} (true 또는 false)")


def _number(data: dict[str, Any], key: str, default, low, high, cast: Callable):
    value = data.get(key)
    if value is None or value == "":
        return default
    try:
        number = cast(value)
    except (TypeError, ValueError):
        raise Scan2DocError(f"{key} 값이 숫자가 아닙니다: {value}") from None
    if not low <= number <= high:
        raise Scan2DocError(f"{key} 값은 {low}~{high} 사이여야 합니다: {number}")
    return number


def _int(data: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    return _number(data, key, default, low, high, int)


def _float(data: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    return _number(data, key, default, low, high, float)


def _choice(data: dict[str, Any], key: str, allowed: tuple[str, ...], default: str) -> str:
    value = data.get(key)
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text not in allowed:
        raise Scan2DocError(f"{key} 값이 잘못됐습니다: {value} (가능: {', '.join(allowed)})")
    return text


def _text(value: Any, *, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > limit:
        raise Scan2DocError(f"값이 너무 깁니다({len(text)}자, 최대 {limit}자).")
    # 제어 문자는 문서에 그대로 들어가면 곤란하다.
    return "".join(ch for ch in text if ch == "\t" or ch >= " ")


__all__ = ["WEB_FORMATS", "check_supported", "parse_options", "safe_filename"]

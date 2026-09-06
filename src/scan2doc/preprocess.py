"""OCR 인식률을 높이기 위한 이미지 보정.

numpy/opencv가 없어도 동작해야 하므로, 없으면 PIL만으로 가능한 보정을
적용하고 나머지는 조용히 건너뛴다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image, ImageOps

from .config import PreprocessOptions

log = logging.getLogger(__name__)

try:  # 선택 의존성
    import cv2
    import numpy as np

    HAVE_CV2 = True
except ImportError:  # pragma: no cover - 환경에 따라 달라짐
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    HAVE_CV2 = False


@dataclass
class PreprocessResult:
    image: Image.Image
    skew: float = 0.0
    scaled: float = 1.0
    steps: tuple[str, ...] = ()


def preprocess(image: Image.Image, options: PreprocessOptions) -> PreprocessResult:
    """설정에 따라 보정 단계를 차례로 적용한다."""
    steps: list[str] = []
    img = ImageOps.exif_transpose(image)  # 휴대폰 사진의 회전 정보 반영
    if img is not image:
        steps.append("exif")

    if not options.enabled:
        return PreprocessResult(image=img, steps=tuple(steps))

    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")

    scale = 1.0
    if img.width < options.upscale_min_width:
        scale = options.upscale_target_width / max(1, img.width)
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
        steps.append(f"upscale x{scale:.2f}")

    if options.grayscale:
        img = ImageOps.grayscale(img)
        steps.append("grayscale")

    skew = 0.0
    if HAVE_CV2:
        arr = _to_array(img)
        if options.denoise:
            arr = _denoise(arr)
            steps.append("denoise")
        if options.deskew:
            skew = detect_skew(arr, options.max_skew_deg)
            if abs(skew) >= 0.15:
                arr = _rotate(arr, skew)
                steps.append(f"deskew {skew:+.2f}°")
        if options.binarize:
            arr = _binarize(arr)
            steps.append("binarize")
        img = _to_image(arr)
    elif options.deskew or options.binarize or options.denoise:
        log.debug("opencv/numpy가 없어 기울기 보정·이진화를 건너뜁니다.")

    if options.enabled and not options.binarize:
        img = ImageOps.autocontrast(img.convert("L") if img.mode != "L" else img)
        steps.append("autocontrast")

    return PreprocessResult(image=img, skew=skew, scaled=scale, steps=tuple(steps))


# --- opencv 기반 세부 단계 ------------------------------------------------

def _to_array(img: Image.Image):
    if img.mode != "L":
        img = ImageOps.grayscale(img)
    return np.array(img)


def _to_image(arr) -> Image.Image:
    return Image.fromarray(arr)


def _denoise(arr):
    return cv2.fastNlMeansDenoising(arr, None, h=7, templateWindowSize=7, searchWindowSize=21)


def _binarize(arr):
    # 조명이 고르지 않은 사진에 강한 적응형 이진화.
    return cv2.adaptiveThreshold(
        arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=31, C=15
    )


def detect_skew(arr, max_deg: float = 15.0) -> float:
    """텍스트 픽셀 덩어리의 최소 외접 사각형으로 기울기(도)를 추정한다."""
    inverted = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(inverted)
    if coords is None or len(coords) < 50:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    # minAreaRect는 0~90도를 주므로 -45~45도 범위로 정규화한다.
    if angle > 45:
        angle -= 90
    if abs(angle) > max_deg:
        return 0.0
    return float(angle)


def _rotate(arr, angle: float):
    h, w = arr.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        arr, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

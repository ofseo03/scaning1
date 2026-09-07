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


#: OSD가 알려 준 각도를 화질 손실 없이 되돌리기 위한 대응표.
#: OSD의 값은 "시계 방향으로 이만큼 돌리면 똑바로 선다"는 뜻이고,
#: PIL의 ROTATE_* 는 반시계 방향이다.
ROTATION_TRANSPOSE = {
    90: Image.ROTATE_270,
    180: Image.ROTATE_180,
    270: Image.ROTATE_90,
}


def rotate_image(image: Image.Image, degrees: int) -> Image.Image:
    """쪽 전체를 degrees 만큼(시계 방향) 돌려 바로 세운다."""
    transpose = ROTATION_TRANSPOSE.get(degrees % 360)
    if transpose is not None:
        return image.transpose(transpose)  # 90도 단위는 무손실로 돌린다
    return image.rotate(-degrees, expand=True, resample=Image.BICUBIC, fillcolor="white")


@dataclass
class PreprocessResult:
    image: Image.Image
    skew: float = 0.0
    scaled: float = 1.0
    steps: tuple[str, ...] = ()


def has_alpha(image: Image.Image) -> bool:
    """투명도를 담고 있는 이미지인지."""
    return image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )


def flatten_alpha(image: Image.Image) -> Image.Image:
    """투명한 부분을 흰 종이 위에 얹은 것처럼 채운다.

    투명도가 있는 이미지를 그냥 convert("RGB")로 바꾸면 투명한 부분의 색이
    그대로 드러나 대개 검게 변한다. 창 모서리가 둥근 화면 캡처 PNG처럼
    투명한 배경 위에 검은 글자가 있는 그림은 이때 글자가 배경에 묻혀
    인식되지 않는다. 흰색으로 먼저 채워 두면 그런 일이 없다.
    """
    background = Image.new("RGB", image.size, (255, 255, 255))
    rgba = image.convert("RGBA")
    background.paste(rgba, mask=rgba.split()[-1])
    return background


def preprocess(image: Image.Image, options: PreprocessOptions) -> PreprocessResult:
    """설정에 따라 보정 단계를 차례로 적용한다."""
    steps: list[str] = []
    img = ImageOps.exif_transpose(image)  # 휴대폰 사진의 회전 정보 반영
    if img is not image:
        steps.append("exif")

    # 투명도 처리는 보정을 끄더라도 반드시 해야 한다. 이 단계를 건너뛰면
    # 아래의 convert("RGB")가 투명한 배경을 검게 만들어 글자를 지워 버린다.
    if has_alpha(img):
        img = flatten_alpha(img)
        steps.append("flatten-alpha")

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

    # 이진화·노이즈 제거는 회색조에서만 할 수 있다.
    use_gray = options.grayscale or options.binarize or options.denoise
    if use_gray:
        if not options.grayscale:
            log.debug("이진화·노이즈 제거를 켜 두어 회색조로 바꿉니다.")
        img = ImageOps.grayscale(img)
        steps.append("grayscale")

    skew = 0.0
    if HAVE_CV2:
        if use_gray:
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
        elif options.deskew:
            # 색을 그대로 둘 때도 기울기는 회색조 복사본으로 재고, 돌리기는 색 그림에 한다.
            skew = detect_skew(_to_array(img), options.max_skew_deg)
            if abs(skew) >= 0.15:
                img = _to_image(_rotate(np.array(img), skew))
                steps.append(f"deskew {skew:+.2f}°")
    elif options.deskew or options.binarize or options.denoise:
        log.debug("opencv/numpy가 없어 기울기 보정·이진화를 건너뜁니다.")

    if not options.binarize:
        # 색을 그대로 두기로 했으면 여기서도 색을 지우지 않는다.
        # (autocontrast 는 RGB 면 채널마다 따로 늘린다.)
        img = ImageOps.autocontrast(img)
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

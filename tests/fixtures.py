"""테스트용 가짜 스캔 이미지 생성기.

한국어 글꼴이 있는 환경에서만 실제 OCR 테스트를 돌린다.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: 흔한 한국어 글꼴 후보들
KOREAN_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "C:/Windows/Fonts/malgun.ttf",
]

SAMPLE_LINES = [
    ("제1장 총칙", 44, True),
    ("", 20, False),
    ("제1조 (목적) 이 규정은 회사의 문서 관리에 관한", 26, False),
    ("기본적인 사항을 정함을 목적으로 한다.", 26, False),
    ("", 14, False),
    ("- 첫째, 모든 문서는 전자적으로 보관한다.", 26, False),
    ("- 둘째, 보존 기간은 5년으로 한다.", 26, False),
    ("", 14, False),
    ("Contact: office@example.com  Tel 02-1234-5678", 24, False),
]


def find_korean_font() -> str | None:
    for candidate in KOREAN_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def make_sample_image(
    path: Path,
    *,
    lines=SAMPLE_LINES,
    width: int = 1240,
    rotate: float = 0.0,
) -> Path | None:
    """한국어 문서를 흉내 낸 스캔 이미지를 만든다. 글꼴이 없으면 None."""
    font_path = find_korean_font()
    if font_path is None:
        return None

    height = 120 + sum(size + 18 for _, size, _ in lines)
    image = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)

    y = 60
    for text, size, bold in lines:
        if text:
            font = ImageFont.truetype(font_path, size)
            draw.text((90, y), text, fill=20, font=font)
            if bold:  # 굵게 흉내: 살짝 겹쳐 그리기
                draw.text((91, y), text, fill=20, font=font)
        y += size + 18

    if rotate:
        image = image.rotate(rotate, expand=True, fillcolor=255, resample=Image.BICUBIC)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, dpi=(300, 300))
    return path


def make_sample_pdf(path: Path, *, pages: int = 2, with_text_layer: bool = True) -> Path | None:
    """텍스트 레이어가 있는 PDF(디지털 원본)를 만든다."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return None

    font_path = find_korean_font()
    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page()
        if with_text_layer:
            if font_path:
                page.insert_font(fontname="kor", fontfile=font_path)
                page.insert_text((72, 100), f"제{index + 1}장 시험 문서", fontname="kor", fontsize=22)
                page.insert_text((72, 140), "한글 텍스트 레이어가 들어 있는 PDF입니다.",
                                 fontname="kor", fontsize=12)
            else:
                page.insert_text((72, 100), f"Chapter {index + 1}", fontsize=22)
                page.insert_text((72, 140), "PDF with an embedded text layer.", fontsize=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    return path

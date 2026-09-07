"""입력 파일 수집과 페이지 단위 적재.

이미지(JPG/PNG/…), 여러 장이 담긴 TIFF, PDF를 모두 '페이지의 나열'로 바꾼다.
PDF에 이미 글자 레이어가 있으면 OCR 없이 그대로 뽑아내는 것이 훨씬 정확하므로
그 경로도 함께 제공한다.
"""

from __future__ import annotations

import glob
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

from PIL import Image, ImageSequence

from .config import (
    DOC_SUFFIXES,
    IMAGE_SUFFIXES,
    SUPPORTED_SUFFIXES,
    ConvertOptions,
    parse_page_range,
)
from .errors import InputError
from .model import Block, BlockKind

log = logging.getLogger(__name__)

#: PDF 한 쪽에서 이 정도 글자가 나오면 '텍스트 레이어가 있다'고 본다.
PDF_TEXT_LAYER_MIN_CHARS = 24

#: 장면이 여러 개라도 '여러 쪽'이 아니라 '움직이는 그림'으로 보는 형식
ANIMATION_FORMATS = {"GIF", "WEBP", "APNG", "PNG"}


@dataclass
class LoadedPage:
    """OCR 또는 문서 작성으로 넘길 준비가 된 한 쪽."""

    source: Path
    page_no: int
    """원본 파일 안에서의 쪽 번호(1부터)."""

    image: Image.Image | None = None
    native_blocks: list[Block] | None = None
    """OCR 없이 이미 얻은 문단들(PDF 텍스트 레이어)."""

    width: int = 0
    height: int = 0
    dpi: int = 0
    engine_hint: str = ""
    extras: dict = field(default_factory=dict)

    @property
    def needs_ocr(self) -> bool:
        return self.native_blocks is None


# --- 파일 수집 -----------------------------------------------------------

def _natural_key(path: Path) -> tuple:
    """page2.jpg가 page10.jpg보다 앞에 오도록 하는 정렬 키."""
    parts = re.split(r"(\d+)", path.name.lower())
    return (str(path.parent), tuple(int(p) if p.isdigit() else p for p in parts))


def sniff_kind(path: Path) -> str | None:
    """확장자만으로 알 수 없을 때 파일 내용으로 종류를 알아낸다.

    브라우저에서 '이미지 저장'을 하면 확장자가 없거나(`screenshot`)
    낯선 확장자(`.jfif` 등)로 저장되는 일이 흔하다. 이름 때문에 멀쩡한
    화면 캡처를 돌려보내지 않도록, 열어 보고 판단한다.

    돌려주는 값은 'pdf', 'image', 또는 알 수 없으면 None.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
    except OSError:
        return None
    if head.startswith(b"%PDF"):
        return "pdf"
    try:
        with Image.open(path) as img:
            img.verify()
    except Exception:  # Pillow는 형식마다 다른 예외를 던진다
        return None
    return "image"


def _looks_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES or sniff_kind(path) is not None


def collect_inputs(paths: Sequence[str | Path], *, recursive: bool = False) -> list[Path]:
    """경로·디렉터리·와일드카드를 실제 파일 목록으로 펼친다."""
    found: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: Path) -> None:
        resolved = candidate.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        found.append(candidate)

    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(path.glob(pattern), key=_natural_key):
                if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES:
                    add(child)
        elif path.exists():
            # 확장자가 낯설어도 내용이 이미지나 PDF면 받아들인다.
            if not _looks_supported(path):
                raise InputError(
                    f"지원하지 않는 형식입니다: {path.name} "
                    f"(지원: {', '.join(sorted(SUPPORTED_SUFFIXES))})"
                )
            add(path)
        else:
            # 셸이 확장해 주지 않은 와일드카드를 직접 처리한다.
            # glob 모듈은 절대 경로 패턴도 그대로 받아 준다.
            matches = sorted(
                (Path(m) for m in glob.glob(str(path), recursive=recursive)),
                key=_natural_key,
            )
            usable = [
                m for m in matches
                if m.is_file() and m.suffix.lower() in SUPPORTED_SUFFIXES
            ]
            if not usable:
                raise InputError(f"입력을 찾을 수 없습니다: {path}")
            for match in usable:
                add(match)

    if not found:
        raise InputError("변환할 이미지나 PDF를 찾지 못했습니다.")
    return found


# --- 페이지 적재 ---------------------------------------------------------

def load_pages(path: Path, options: ConvertOptions) -> Iterator[LoadedPage]:
    """파일 하나를 페이지 단위로 읽어 순서대로 내보낸다."""
    suffix = path.suffix.lower()
    kind = None
    if suffix in DOC_SUFFIXES:
        kind = "pdf"
    elif suffix in IMAGE_SUFFIXES:
        kind = "image"
    else:  # 확장자가 없거나 낯선 파일은 내용을 보고 정한다
        kind = sniff_kind(path)

    if kind == "pdf":
        yield from _load_pdf(path, options)
    elif kind == "image":
        yield from _load_image(path, options)
    else:
        raise InputError(f"지원하지 않는 형식입니다: {path}")


def _is_animation(img: Image.Image) -> bool:
    """여러 장이 '움직이는 그림'인지(여러 쪽 문서가 아니라).

    여러 장이 담긴 TIFF는 스캔한 여러 쪽이므로 모두 변환해야 하지만,
    GIF·WEBP·APNG는 대개 화면 녹화나 데모 영상이라 장면마다 쪽을 만들면
    같은 화면이 수백 쪽 반복된다.
    """
    return (img.format or "").upper() in ANIMATION_FORMATS


def _load_image(path: Path, options: ConvertOptions) -> Iterator[LoadedPage]:
    try:
        img = Image.open(path)
    except OSError as exc:
        raise InputError(f"이미지를 열 수 없습니다: {path} ({exc})") from exc

    frames = list(ImageSequence.Iterator(img)) if getattr(img, "n_frames", 1) > 1 else [img]
    if (
        len(frames) > 1
        and _is_animation(img)
        and not options.all_frames
        and not options.pages.strip()
    ):
        log.info(
            "%s: 움직이는 그림이라 첫 장면만 변환합니다(장면 %d개). "
            "모두 변환하려면 --all-frames 를 주세요.",
            path.name, len(frames),
        )
        frames = frames[:1]
    wanted = parse_page_range(options.pages, len(frames))

    for page_no, frame in enumerate(frames, start=1):
        if page_no not in wanted:
            continue
        try:
            copied = frame.copy()
        except OSError as exc:  # 내려받다 만 파일 등 그림이 중간에 끊긴 경우
            raise InputError(
                f"이미지가 손상되었거나 다 내려받지 못한 것 같습니다: {path.name} ({exc})"
            ) from exc
        dpi_info = copied.info.get("dpi") or img.info.get("dpi") or (0, 0)
        yield LoadedPage(
            source=path,
            page_no=page_no,
            image=copied,
            width=copied.width,
            height=copied.height,
            dpi=int(dpi_info[0] or 0),
        )


def _load_pdf(path: Path, options: ConvertOptions) -> Iterator[LoadedPage]:
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError as exc:
            raise InputError(
                "PDF를 읽으려면 pymupdf가 필요합니다: pip install pymupdf"
            ) from exc

    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf는 자체 예외를 던진다
        raise InputError(f"PDF를 열 수 없습니다: {path} ({exc})") from exc

    with doc:
        wanted = parse_page_range(options.pages, doc.page_count)
        for page_no in wanted:
            page = doc[page_no - 1]
            blocks = None
            if options.pdf_text != "never":
                blocks = _pdf_text_blocks(page, options)
                if options.pdf_text == "auto" and blocks is not None:
                    chars = sum(len(b.text) for b in blocks)
                    if chars < PDF_TEXT_LAYER_MIN_CHARS:
                        blocks = None  # 스캔본으로 보고 OCR로 넘긴다

            if blocks is not None:
                rect = page.rect
                yield LoadedPage(
                    source=path,
                    page_no=page_no,
                    native_blocks=blocks,
                    width=int(rect.width),
                    height=int(rect.height),
                    dpi=72,
                    engine_hint="pdf-text",
                )
                continue

            zoom = options.dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            yield LoadedPage(
                source=path,
                page_no=page_no,
                image=image,
                width=pix.width,
                height=pix.height,
                dpi=options.dpi,
            )


def _pdf_text_blocks(page, options: ConvertOptions) -> list[Block] | None:
    """PDF 내장 텍스트 레이어를 문단 블록으로 바꾼다.

    글자 크기를 알 수 있으므로 제목 판별이 OCR보다 정확하다.
    """
    try:
        data = page.get_text("dict")
    except Exception:  # pragma: no cover - 손상된 PDF
        return None

    sizes: list[float] = []
    raw_blocks: list[tuple[str, float, bool]] = []

    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 = 텍스트, 1 = 이미지
            continue
        lines: list[str] = []
        block_sizes: list[float] = []
        bold = False
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans)
            if text.strip():
                lines.append(text)
            for span in spans:
                if span.get("text", "").strip():
                    block_sizes.append(float(span.get("size", 0)))
                    if "bold" in str(span.get("font", "")).lower():
                        bold = True
        if not lines:
            continue
        from .model import join_lines

        merged = "\n".join(lines) if options.keep_line_breaks else join_lines(lines)
        size = max(block_sizes) if block_sizes else 0.0
        sizes.extend(block_sizes)
        raw_blocks.append((merged, size, bold))

    if not raw_blocks:
        return None

    body_size = sorted(sizes)[len(sizes) // 2] if sizes else 0.0
    blocks: list[Block] = []
    for text, size, bold in raw_blocks:
        kind = BlockKind.PARAGRAPH
        level = 0
        if options.detect_headings and body_size > 0:
            ratio = size / body_size
            if ratio >= 1.5 or (ratio >= 1.15 and bold and len(text) <= 80):
                kind = BlockKind.HEADING
                level = 1 if ratio >= 1.8 else (2 if ratio >= 1.3 else 3)
        blocks.append(Block(kind=kind, level=level, text_override=text))

    if options.detect_lists:
        from .layout import classify_list_blocks

        blocks = classify_list_blocks(blocks)
    return blocks

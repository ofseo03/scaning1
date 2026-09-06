"""입력 → OCR → 문서 모델 → 파일 저장까지의 전체 흐름."""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageOps

from .config import ConvertOptions
from .errors import InputError, Scan2DocError
from .inputs import LoadedPage, collect_inputs, load_pages
from .layout import build_blocks
from .model import Document, Page
from .ocr import get_engine
from .ocr.base import OcrEngine
from .preprocess import preprocess
from .writers import get_writer

log = logging.getLogger(__name__)

#: 진행 상황 콜백: (단계, 사람이 읽을 메시지, 진행률 0.0~1.0)
ProgressCallback = Callable[[str, str, float], None]


@dataclass
class ConversionResult:
    """입력 하나(또는 병합된 묶음)에 대한 변환 결과."""

    document: Document
    outputs: list[Path] = field(default_factory=list)
    sources: list[Path] = field(default_factory=list)
    elapsed: float = 0.0
    ocr_pages: int = 0
    text_layer_pages: int = 0

    @property
    def page_count(self) -> int:
        return len(self.document.pages)

    @property
    def confidence(self) -> float:
        return self.document.confidence


def convert(
    inputs: Sequence[str | Path],
    options: ConvertOptions,
    progress: ProgressCallback | None = None,
) -> list[ConversionResult]:
    """입력 목록을 변환하고 결과를 돌려준다."""
    files = collect_inputs(inputs, recursive=options.recursive)
    engine = get_engine(options.engine)

    # OCR이 실제로 필요한지는 페이지를 열어 봐야 알지만, 미리 확인해 두면
    # 설정 오류를 첫 페이지가 아니라 시작 시점에 알려 줄 수 있다.
    if _may_need_ocr(files, options):
        _check_engine(engine, options)

    with tempfile.TemporaryDirectory(prefix="scan2doc-") as tmpdir:
        workdir = Path(tmpdir)
        if options.merge:
            return [_convert_merged(files, engine, options, workdir, progress)]
        return [
            _convert_single(path, engine, options, workdir, progress, index, len(files))
            for index, path in enumerate(files)
        ]


def _may_need_ocr(files: Sequence[Path], options: ConvertOptions) -> bool:
    if options.pdf_text == "always" and all(f.suffix.lower() == ".pdf" for f in files):
        return False
    return True


def _check_engine(engine: OcrEngine, options: ConvertOptions) -> None:
    try:
        engine.check(options)  # type: ignore[call-arg]
    except TypeError:  # check()가 옵션을 받지 않는 엔진
        engine.check()


def _convert_single(
    path: Path,
    engine: OcrEngine,
    options: ConvertOptions,
    workdir: Path,
    progress: ProgressCallback | None,
    index: int,
    total: int,
) -> ConversionResult:
    started = time.perf_counter()
    document = Document(
        title=options.title or "",
        language=options.language,
        meta={"source": str(path)},
    )
    result = ConversionResult(document=document, sources=[path])

    _process_file(path, document, result, engine, options, workdir, progress,
                  base_index=index, base_total=total)

    result.elapsed = time.perf_counter() - started
    result.outputs = _write_outputs(document, _output_base(path, options), options, progress)
    return result


def _convert_merged(
    files: Sequence[Path],
    engine: OcrEngine,
    options: ConvertOptions,
    workdir: Path,
    progress: ProgressCallback | None,
) -> ConversionResult:
    started = time.perf_counter()
    document = Document(
        title=options.title or "",
        language=options.language,
        meta={"sources": [str(f) for f in files]},
    )
    result = ConversionResult(document=document, sources=list(files))

    for index, path in enumerate(files):
        _process_file(path, document, result, engine, options, workdir, progress,
                      base_index=index, base_total=len(files))

    result.elapsed = time.perf_counter() - started
    base = _merged_output_base(files, options)
    result.outputs = _write_outputs(document, base, options, progress)
    return result


def _process_file(
    path: Path,
    document: Document,
    result: ConversionResult,
    engine: OcrEngine,
    options: ConvertOptions,
    workdir: Path,
    progress: ProgressCallback | None,
    *,
    base_index: int,
    base_total: int,
) -> None:
    for loaded in load_pages(path, options):
        page_index = len(document.pages)
        _report(
            progress, "page",
            f"{path.name} · {loaded.page_no}쪽 처리 중",
            (base_index + 0.5) / max(1, base_total),
        )
        page = _process_page(loaded, engine, options, workdir, page_index)
        document.pages.append(page)
        if loaded.needs_ocr:
            result.ocr_pages += 1
        else:
            result.text_layer_pages += 1

    if not document.pages:
        raise InputError(f"읽을 수 있는 쪽이 없습니다: {path}")


def _process_page(
    loaded: LoadedPage,
    engine: OcrEngine,
    options: ConvertOptions,
    workdir: Path,
    page_index: int,
) -> Page:
    page = Page(
        index=page_index,
        width=loaded.width,
        height=loaded.height,
        dpi=loaded.dpi,
        source=str(loaded.source),
        source_page=loaded.page_no,
    )

    if not loaded.needs_ocr:
        page.blocks = loaded.native_blocks or []
        page.engine = "pdf-text"
        return page

    assert loaded.image is not None
    image = ImageOps.exif_transpose(loaded.image) or loaded.image

    # 회전은 기울기 보정보다 먼저 해야 한다. 90도 누운 쪽에서 기울기를 재면
    # 엉뚱한 각도가 나오기 때문이다.
    if options.preprocess.enabled and options.preprocess.auto_rotate:
        rotation = _detect_rotation(engine, image, options)
        if rotation:
            image = _apply_rotation(image, rotation)
            page.rotation = rotation

    prepared = preprocess(image, options.preprocess)
    image = prepared.image
    page.skew = prepared.skew

    ocr = engine.recognize(image, options)
    page.engine = ocr.engine or engine.name
    page.blocks = build_blocks(ocr.records, options)
    page.width, page.height = image.width, image.height

    if options.embed_image:
        page.image_path = _save_page_image(loaded.image, workdir, page_index)
    return page


def _detect_rotation(engine: OcrEngine, image: Image.Image, options: ConvertOptions) -> int:
    detector = getattr(engine, "detect_orientation", None)
    if detector is None:
        return 0
    try:
        return detector(image, options) % 360
    except Exception as exc:  # OSD 실패가 변환을 막지 않게 한다
        log.debug("회전 감지 실패(무시): %s", exc)
        return 0


#: OSD가 알려 준 각도를 화질 손실 없이 되돌리기 위한 대응표.
#: OSD의 값은 "시계 방향으로 이만큼 돌리면 똑바로 선다"는 뜻이고,
#: PIL의 ROTATE_* 는 반시계 방향이다.
_ROTATION_TRANSPOSE = {
    90: Image.ROTATE_270,
    180: Image.ROTATE_180,
    270: Image.ROTATE_90,
}


def _apply_rotation(image: Image.Image, degrees: int) -> Image.Image:
    transpose = _ROTATION_TRANSPOSE.get(degrees % 360)
    if transpose is not None:
        return image.transpose(transpose)  # 90도 단위는 무손실로 돌린다
    return image.rotate(-degrees, expand=True, resample=Image.BICUBIC, fillcolor="white")


def _save_page_image(image: Image.Image, workdir: Path, index: int) -> str:
    target = workdir / f"page-{index:04d}.png"
    rgb = image.convert("RGB") if image.mode not in ("RGB", "L") else image
    rgb.save(target, format="PNG")
    return str(target)


# --- 출력 경로와 저장 -----------------------------------------------------

def _output_base(source: Path, options: ConvertOptions) -> Path:
    """확장자를 뺀 출력 기본 경로."""
    if options.output is None:
        return source.with_suffix("")
    out = options.output
    if out.is_dir() or str(out).endswith(("/", "\\")) or not out.suffix:
        out.mkdir(parents=True, exist_ok=True)
        return out / source.stem
    out.parent.mkdir(parents=True, exist_ok=True)
    return out.with_suffix("")


def _merged_output_base(files: Sequence[Path], options: ConvertOptions) -> Path:
    if options.output is not None:
        return _output_base(files[0], options)
    first = files[0]
    return first.with_name(f"{first.stem}_외{len(files) - 1}건" if len(files) > 1 else first.stem)


def _write_outputs(
    document: Document,
    base: Path,
    options: ConvertOptions,
    progress: ProgressCallback | None,
) -> list[Path]:
    outputs: list[Path] = []
    for fmt in options.formats:
        name = "hwpx" if fmt == "hwp" and options.hwp_format == "hwpx" else fmt
        if fmt == "hwp":
            name = options.hwp_format
        writer = get_writer(name)
        target = writer.target_path(base)
        if target.exists() and not options.overwrite:
            target = _unique_path(target)
        _report(progress, "write", f"{target.name} 저장 중", 0.95)
        writer.write(document, target, options)
        outputs.append(target)

    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(document.to_json(), encoding="utf-8")
        outputs.append(options.report)
    return outputs


def _unique_path(path: Path) -> Path:
    """같은 이름이 있으면 (1), (2) … 를 붙인다."""
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _report(progress: ProgressCallback | None, stage: str, message: str, ratio: float) -> None:
    if progress is not None:
        try:
            progress(stage, message, max(0.0, min(1.0, ratio)))
        except Exception:  # 진행 표시 오류가 변환을 막지 않게 한다
            log.debug("진행 콜백 오류", exc_info=True)


__all__ = ["ConversionResult", "convert", "ProgressCallback", "Scan2DocError"]

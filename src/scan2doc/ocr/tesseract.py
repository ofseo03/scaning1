"""Tesseract OCR 엔진 어댑터.

tesseract 실행 파일을 직접 부른다. 한 번의 실행으로 txt와 tsv를 함께 받아
좌표(tsv)와 띄어쓰기가 정확한 문장(txt)을 모두 얻기 위해서다.

한국어에서는 tsv의 '낱말'이 음절 단위로 쪼개지는 일이 잦은데,
같은 실행의 txt 출력에는 띄어쓰기가 제대로 들어 있다. 두 결과를 줄 단위로
맞춰 붙이면 좌표는 좌표대로, 문장은 문장대로 살릴 수 있다.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from ..config import ConvertOptions
from ..errors import DependencyError, OcrError
from ..layout import WordRecord
from ..model import BBox
from ..preprocess import ROTATION_TRANSPOSE
from .base import OcrEngine, OcrResult

log = logging.getLogger(__name__)

#: 윈도우에서 흔한 설치 경로
WINDOWS_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

INSTALL_HELP = (
    "Tesseract 실행 파일을 찾을 수 없습니다.\n"
    "  · Ubuntu/Debian: sudo apt install tesseract-ocr tesseract-ocr-kor\n"
    "  · Fedora       : sudo dnf install tesseract tesseract-langpack-kor\n"
    "  · macOS        : brew install tesseract tesseract-lang\n"
    "  · Windows      : https://github.com/UB-Mannheim/tesseract/wiki 설치 후\n"
    '                   --tesseract-cmd "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"'
)

#: --psm auto 일 때 시도할 순서.
#: 4(변동 글자 크기의 한 단 문서)는 한국어 문서에서 3(전체 자동)보다 훨씬 안정적이다.
AUTO_PSM_CANDIDATES = (4, 3)
#: 1차 결과가 이 정도면 충분하다고 보고 2차 시도를 생략한다.
AUTO_GOOD_CONFIDENCE = 85.0

_OSD_ROTATE_RE = re.compile(r"^Rotate:\s*(\d+)", re.MULTILINE)

#: 회전 판정을 확인할 때 쓸 축소 폭(픽셀).
#: 방향만 가리면 되므로 작게 줄여 빠르게 확인한다.
ROTATION_CHECK_WIDTH = 1000
#: 돌린 쪽이 이 배수 이상 나아야 실제로 돌린다.
ROTATION_CHECK_MARGIN = 1.2


class TesseractEngine(OcrEngine):
    name = "tesseract"
    description = "Tesseract OCR (기본값, 한국어는 tesseract-ocr-kor 필요)"

    # --- 실행 파일 찾기 ---------------------------------------------------

    def resolve_cmd(self, options: ConvertOptions | None = None) -> str:
        options = options or ConvertOptions()
        candidates = [
            options.tesseract_cmd,
            os.environ.get("SCAN2DOC_TESSERACT"),
            "tesseract",
        ]
        for candidate in candidates:
            if candidate and (shutil.which(candidate) or Path(candidate).is_file()):
                return candidate
        for path in WINDOWS_PATHS:
            if Path(path).is_file():
                return path
        raise DependencyError(INSTALL_HELP)

    def check(self, options: ConvertOptions | None = None) -> None:
        cmd = self.resolve_cmd(options)
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DependencyError(f"Tesseract 실행에 실패했습니다: {exc}") from exc

    def version(self, options: ConvertOptions | None = None) -> str:
        cmd = self.resolve_cmd(options)
        out = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, timeout=30
        ).stdout
        first = out.splitlines()[0] if out else ""
        return first.replace("tesseract", "").strip() or "알 수 없음"

    def languages(self, options: ConvertOptions | None = None) -> list[str]:
        cmd = self.resolve_cmd(options)
        try:
            out = subprocess.run(
                [cmd, "--list-langs"], capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover
            return []
        # 첫 줄은 "List of available languages ..." 안내문이다.
        lines = (out.stdout or out.stderr or "").splitlines()
        return sorted(line.strip() for line in lines[1:] if line.strip())

    # --- 인식 -------------------------------------------------------------

    def recognize(self, image: Image.Image, options: ConvertOptions) -> OcrResult:
        modes = _psm_candidates(options.psm)
        best: OcrResult | None = None
        best_score = -1.0

        for psm in modes:
            result = self._recognize_once(image, options, psm)
            score = _score(result)
            if score > best_score:
                best, best_score = result, score
            if result.confidence >= AUTO_GOOD_CONFIDENCE and result.records:
                break  # 충분히 좋으면 다음 후보는 시도하지 않는다

        return best or OcrResult(engine=self.name)

    def _recognize_once(
        self, image: Image.Image, options: ConvertOptions, psm: int
    ) -> OcrResult:
        outputs = self._run(image, options, psm, ("tsv", "txt"))
        records = records_from_tsv(outputs["tsv"], options.min_confidence)
        _attach_line_text(records, outputs.get("txt", ""))
        return OcrResult(records=records, engine=self.name, psm=psm)

    def detect_orientation(self, image: Image.Image, options: ConvertOptions) -> int:
        """OSD로 쪽 회전을 감지한다. 실패하면 0."""
        try:
            outputs = self._run(image, options, psm=0, extensions=("osd",), osd=True)
        except (OcrError, DependencyError) as exc:
            log.debug("OSD 회전 감지 실패(무시): %s", exc)
            return 0
        match = _OSD_ROTATE_RE.search(outputs.get("osd", ""))
        rotation = int(match.group(1)) % 360 if match else 0
        if rotation == 0:
            return 0
        return self._confirm_rotation(image, options, rotation)

    def _confirm_rotation(
        self, image: Image.Image, options: ConvertOptions, rotation: int
    ) -> int:
        """OSD가 알려 준 각도를 실제로 읽어 보고 확인한다.

        OSD는 글줄이 길게 이어지는 문서를 전제로 만들어졌다. 화면 캡처처럼
        짧은 글과 기호가 흩어진 그림에서는 똑바로 선 쪽을 180도라 하거나
        왼쪽/오른쪽을 뒤바꿔 말하는 일이 잦고, 그 말을 그대로 따르면
        멀쩡한 화면이 거꾸로 뒤집힌 문서가 나온다.

        그래서 작게 줄인 그림으로 후보 각도를 실제로 읽어 보고, 원본보다
        뚜렷하게 나을 때만 돌린다.
        """
        small = image
        if image.width > ROTATION_CHECK_WIDTH:
            ratio = ROTATION_CHECK_WIDTH / image.width
            small = image.resize(
                (ROTATION_CHECK_WIDTH, max(1, int(image.height * ratio))), Image.LANCZOS
            )

        # OSD가 90/270을 뒤바꿔 말하는 일이 있어 반대쪽도 함께 견준다.
        candidates = [rotation]
        if rotation in (90, 270):
            candidates.append(360 - rotation)

        try:
            upright = _score(self._recognize_once(small, options, psm=3))
            scored = {
                angle: _score(
                    self._recognize_once(
                        small.transpose(ROTATION_TRANSPOSE[angle]), options, psm=3
                    )
                )
                for angle in candidates
            }
        except (OcrError, DependencyError) as exc:
            log.debug("회전 확인 실패(그대로 둠): %s", exc)
            return 0

        best = max(scored, key=lambda angle: scored[angle])
        if scored[best] <= upright * ROTATION_CHECK_MARGIN:
            log.debug("OSD는 %d도라 했지만 읽어 보니 그대로가 낫습니다.", rotation)
            return 0
        if best != rotation:
            log.debug("OSD는 %d도라 했지만 %d도가 더 잘 읽힙니다.", rotation, best)
        return best

    def _run(
        self,
        image: Image.Image,
        options: ConvertOptions,
        psm: int,
        extensions: tuple[str, ...],
        *,
        osd: bool = False,
    ) -> dict[str, str]:
        """tesseract를 한 번 실행하고 요청한 출력들을 문자열로 돌려준다."""
        cmd = self.resolve_cmd(options)
        with tempfile.TemporaryDirectory(prefix="scan2doc-ocr-") as tmp:
            workdir = Path(tmp)
            source = workdir / "page.png"
            _save_for_ocr(image, source)
            base = workdir / "result"

            argv = [cmd, str(source), str(base)]
            argv += ["-l", "osd" if osd else options.language]
            argv += ["--oem", str(options.oem), "--psm", str(psm)]
            if not osd:
                argv += ["-c", "preserve_interword_spaces=1"]
            argv += list(extensions)

            try:
                completed = subprocess.run(
                    argv, capture_output=True, text=True, timeout=options.ocr_timeout
                )
            except subprocess.TimeoutExpired as exc:
                raise OcrError(
                    f"Tesseract가 {options.ocr_timeout}초 안에 끝나지 않았습니다. "
                    "--dpi 를 낮추거나 --ocr-timeout 을 늘려 보세요."
                ) from exc
            except OSError as exc:
                raise OcrError(f"Tesseract 실행에 실패했습니다: {exc}") from exc

            if completed.returncode != 0:
                detail = (completed.stderr or "").strip().splitlines()
                hint = detail[-1] if detail else f"종료 코드 {completed.returncode}"
                if "Failed loading language" in (completed.stderr or ""):
                    hint += (
                        f"\n  → '{options.language}' 언어 데이터가 없습니다. "
                        "예) sudo apt install tesseract-ocr-kor"
                    )
                raise OcrError(f"Tesseract 인식에 실패했습니다: {hint}")

            outputs: dict[str, str] = {}
            for ext in extensions:
                path = base.with_suffix(f".{ext}")
                outputs[ext] = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            return outputs


def _save_for_ocr(image: Image.Image, path: Path) -> None:
    """OCR에 넘기기 좋은 형태(팔레트·알파 제거)로 저장한다."""
    if image.mode in ("P", "RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    elif image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    image.save(path, format="PNG")


def _psm_candidates(psm: int | str) -> tuple[int, ...]:
    if str(psm).strip().lower() == "auto":
        return AUTO_PSM_CANDIDATES
    return (int(psm),)


def _score(result: OcrResult) -> float:
    """결과의 좋고 나쁨을 견주기 위한 점수: 글자 수 × 신뢰도."""
    return sum(
        len(r.text) * (r.confidence if r.confidence >= 0 else 50) / 100
        for r in result.records
    )


def records_from_tsv(tsv: str, min_confidence: float = 0.0) -> list[WordRecord]:
    """tesseract TSV 출력을 WordRecord 목록으로 바꾼다."""
    records: list[WordRecord] = []
    lines = tsv.splitlines()
    if not lines:
        return records

    header = lines[0].split("\t")
    try:
        idx = {name: header.index(name) for name in (
            "level", "block_num", "par_num", "line_num",
            "left", "top", "width", "height", "conf", "text",
        )}
    except ValueError:  # 예상과 다른 형식이면 조용히 포기한다
        log.debug("알 수 없는 TSV 형식: %s", lines[0])
        return records

    for raw in lines[1:]:
        if not raw.strip():
            continue
        fields = raw.split("\t")
        if len(fields) <= idx["text"]:
            continue
        if fields[idx["level"]] != "5":  # 5 = 낱말
            continue
        text = fields[idx["text"]].strip()
        if not text:
            continue
        try:
            conf = float(fields[idx["conf"]])
        except ValueError:
            conf = -1.0
        if min_confidence > 0 and 0 <= conf < min_confidence:
            continue
        try:
            records.append(
                WordRecord(
                    text=text,
                    bbox=BBox(
                        int(fields[idx["left"]]),
                        int(fields[idx["top"]]),
                        int(fields[idx["width"]]),
                        int(fields[idx["height"]]),
                    ),
                    confidence=conf,
                    block_num=int(fields[idx["block_num"]]),
                    par_num=int(fields[idx["par_num"]]),
                    line_num=int(fields[idx["line_num"]]),
                )
            )
        except ValueError:
            continue
    return records


def _attach_line_text(records: list[WordRecord], txt: str) -> None:
    """같은 실행의 txt 출력에서 줄 문장을 가져와 각 낱말에 붙여 둔다.

    줄 수가 정확히 맞을 때만 사용한다. 어긋나면 좌표 기반 이어붙이기로
    되돌아가는 편이 잘못 짝지어진 문장을 쓰는 것보다 안전하다.
    """
    if not records or not txt.strip():
        return

    keys: list[tuple[int, int, int]] = []
    for rec in records:
        key = (rec.block_num, rec.par_num, rec.line_num)
        if not keys or keys[-1] != key:
            keys.append(key)

    text_lines = [line.strip() for line in txt.splitlines() if line.strip()]
    if len(text_lines) != len(keys):
        log.debug("txt(%d줄)와 tsv(%d줄)가 맞지 않아 좌표로 이어붙입니다.",
                  len(text_lines), len(keys))
        return

    mapping = dict(zip(keys, text_lines))
    for rec in records:
        rec.line_text = mapping.get((rec.block_num, rec.par_num, rec.line_num))

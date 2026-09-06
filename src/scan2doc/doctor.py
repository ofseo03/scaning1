"""실행 환경 점검 (scan2doc doctor)."""

from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import dataclass

from .config import ConvertOptions

OK = "✅"
WARN = "⚠️ "
FAIL = "❌"

#: (모듈명, 표시 이름, 필수 여부, 없을 때 안내)
PYTHON_DEPS = [
    ("PIL", "Pillow", True, "pip install pillow"),
    ("docx", "python-docx", True, "pip install python-docx"),
    ("pymupdf", "PyMuPDF", False, "pip install pymupdf  (PDF 입력에 필요)"),
    ("numpy", "NumPy", False, "pip install numpy  (기울기 보정·이진화에 필요)"),
    ("cv2", "OpenCV", False, "pip install opencv-python-headless  (기울기 보정·이진화)"),
    ("tkinter", "tkinter", False, "GUI를 쓰려면 python3-tk 설치 (sudo apt install python3-tk)"),
]

TESSERACT_INSTALL_HELP = """\
Tesseract 설치 방법
  · Ubuntu/Debian : sudo apt install tesseract-ocr tesseract-ocr-kor
  · Fedora        : sudo dnf install tesseract tesseract-langpack-kor
  · macOS         : brew install tesseract tesseract-lang
  · Windows       : https://github.com/UB-Mannheim/tesseract/wiki 에서 설치한 뒤
                    --tesseract-cmd "C:\\Program Files\\Tesseract-OCR\\tesseract.exe" 지정"""


@dataclass
class CheckResult:
    ok: bool
    lines: list[str]


def run_doctor(options: ConvertOptions | None = None) -> CheckResult:
    """필요한 구성 요소를 점검하고 사람이 읽을 보고서를 만든다."""
    options = options or ConvertOptions()
    lines: list[str] = ["scan2doc 환경 점검", "=" * 40, ""]
    ok = True

    lines.append(f"{OK} Python {sys.version.split()[0]}")
    lines.append("")
    lines.append("파이썬 패키지")
    for module, label, required, hint in PYTHON_DEPS:
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", "")
            lines.append(f"  {OK} {label} {version}".rstrip())
        except ImportError:
            if required:
                ok = False
                lines.append(f"  {FAIL} {label} 없음 → {hint}")
            else:
                lines.append(f"  {WARN}{label} 없음 → {hint}")

    lines += ["", "OCR 엔진"]
    tess_ok, tess_lines = _check_tesseract(options)
    ok = ok and tess_ok
    lines += [f"  {line}" for line in tess_lines]

    lines += ["", "출력 형식"]
    from .writers import describe_writers

    for name, ext, desc in describe_writers():
        lines.append(f"  {OK} {name:<6} {ext:<7} {desc}")

    lines += ["", "-" * 40]
    lines.append("모든 준비가 끝났습니다." if ok else "위의 ❌ 항목을 먼저 해결해 주세요.")
    return CheckResult(ok=ok, lines=lines)


def _check_tesseract(options: ConvertOptions) -> tuple[bool, list[str]]:
    from .ocr.tesseract import TesseractEngine

    engine = TesseractEngine()
    try:
        engine.check(options)
    except Exception as exc:
        return False, [f"{FAIL} Tesseract 사용 불가", *str(exc).splitlines(), "", *TESSERACT_INSTALL_HELP.splitlines()]

    lines = [f"{OK} Tesseract {engine.version(options)}"]
    langs = engine.languages(options)
    if langs:
        lines.append(f"{OK} 설치된 언어: {', '.join(langs)}")
        if "kor" not in langs:
            lines.append(
                f"{WARN}한국어 데이터(kor)가 없습니다 → "
                "sudo apt install tesseract-ocr-kor"
            )
    cmd = options.tesseract_cmd or shutil.which("tesseract")
    if cmd:
        lines.append(f"{OK} 실행 파일: {cmd}")
    return True, lines

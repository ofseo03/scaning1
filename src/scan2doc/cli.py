"""명령줄 인터페이스."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import ConvertOptions, PreprocessOptions
from .errors import DependencyError, Scan2DocError
from .ocr import available_engines
from .writers import available_writers, describe_writers

SUBCOMMANDS = {"convert", "doctor", "gui", "serve", "formats"}

EPILOG = """\
사용 예시
  scan2doc 계약서.jpg                        → 계약서.docx + 계약서.hwpx
  scan2doc 사진/ -o 결과/ --merge            → 폴더 전체를 문서 하나로
  scan2doc 보고서.pdf -f docx --pages 1-5    → PDF 1~5쪽만 Word로
  scan2doc 영수증.png -l kor --binarize      → 한국어만, 이진화 후 인식
  scan2doc doctor                            → 설치 상태 점검
  scan2doc gui                               → 창 띄우기
  scan2doc serve                             → 웹 서버 띄우기 (브라우저·휴대폰에서 사용)
"""


def _psm_value(raw: str) -> int | str:
    """--psm 은 'auto' 또는 0~13 사이의 숫자를 받는다."""
    if raw.strip().lower() == "auto":
        return "auto"
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--psm 값이 잘못됐습니다: {raw} (auto 또는 0~13)") from None
    if not 0 <= value <= 13:
        raise argparse.ArgumentTypeError(f"--psm 은 0~13 사이여야 합니다: {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scan2doc",
        description="사진·스크린샷·PDF를 OCR로 읽어 Word(.docx)와 한글(.hwpx) 문서로 바꿉니다.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"scan2doc {__version__}")
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser(
        "convert",
        help="이미지/PDF를 문서로 변환 (기본 명령)",
        description="이미지·PDF를 OCR로 읽어 문서로 저장합니다.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_convert_arguments(convert)

    sub.add_parser("doctor", help="필요한 프로그램이 설치됐는지 점검")
    sub.add_parser("gui", help="간단한 창(GUI) 실행")
    _add_serve_arguments(sub.add_parser(
        "serve",
        help="웹 서버 실행 (브라우저·휴대폰에서 쓰기)",
        description="브라우저에서 파일을 올려 변환할 수 있는 웹 서버를 띄웁니다.",
    ))
    sub.add_parser("formats", help="지원하는 출력 형식 보기")
    return parser


def _add_serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1",
                        help="들을 주소 (기본: 127.0.0.1 — 이 컴퓨터에서만. "
                             "같은 공유기의 휴대폰에서도 쓰려면 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="포트 번호 (기본: 8000)")
    parser.add_argument("--open", dest="open_browser", action="store_true",
                        help="서버를 띄운 뒤 브라우저 열기")
    parser.add_argument("--reload", action="store_true",
                        help="코드가 바뀌면 서버를 다시 띄우기 (개발용)")
    parser.add_argument("--workers", type=int, default=None, metavar="개수",
                        help="동시에 처리할 변환 개수 (기본: 2)")
    parser.add_argument("--max-upload-mb", type=int, default=None, metavar="MB",
                        help="파일 하나의 최대 크기 (기본: 50MB)")
    parser.add_argument("--workspace", type=Path,
                        help="올린 파일과 결과를 둘 폴더 (기본: 임시 폴더)")


def _add_convert_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", metavar="입력",
                        help="이미지 파일, PDF, 또는 폴더")

    out = parser.add_argument_group("출력")
    out.add_argument("-o", "--output", type=Path,
                     help="저장할 파일 또는 폴더 (생략하면 원본 옆에 저장)")
    out.add_argument("-f", "--format", dest="formats", default="docx,hwpx",
                     help=f"출력 형식, 쉼표로 구분 (기본: docx,hwpx / 가능: {', '.join(available_writers())})")
    out.add_argument("--hwp-format", choices=["hwpx", "hwpml"], default="hwpx",
                     help="한글 문서 형식 (기본: hwpx — 한/글 2014 이상)")
    out.add_argument("--merge", action="store_true",
                     help="여러 입력을 문서 하나로 합치기")
    out.add_argument("--overwrite", action="store_true",
                     help="같은 이름의 파일을 덮어쓰기 (기본은 (1) 붙여 새로 저장)")
    out.add_argument("--title", default="", help="문서 맨 앞에 넣을 제목")
    out.add_argument("--report", type=Path,
                     help="인식 결과를 JSON으로도 저장할 경로")

    ocr = parser.add_argument_group("인식(OCR)")
    ocr.add_argument("-l", "--lang", dest="language", default="kor+eng",
                     help="인식 언어 (기본: kor+eng, 예: kor / eng / kor+eng+jpn)")
    ocr.add_argument("--engine", default="tesseract", choices=available_engines(),
                     help="OCR 엔진 (기본: tesseract)")
    ocr.add_argument("--psm", type=_psm_value, default="auto", metavar="auto|숫자",
                     help="페이지 분할 모드 (기본: auto — 4를 먼저 쓰고 필요하면 3으로 재시도. "
                          "4=한 단 문서, 3=여러 단, 6=한 덩어리, 11=흩어진 글자)")
    ocr.add_argument("--oem", type=int, default=3, help="Tesseract 엔진 모드 (기본: 3)")
    ocr.add_argument("--ocr-timeout", type=int, default=180, metavar="초",
                     help="한 쪽당 OCR 제한 시간 (기본: 180초)")
    ocr.add_argument("--tesseract-cmd", help="tesseract 실행 파일 경로 직접 지정")
    ocr.add_argument("--min-confidence", type=float, default=0.0, metavar="0~100",
                     help="이 신뢰도 미만의 낱말은 버림 (기본: 0 = 모두 유지)")

    src = parser.add_argument_group("입력 처리")
    src.add_argument("--dpi", type=int, default=300,
                     help="PDF를 이미지로 만들 해상도 (기본: 300)")
    src.add_argument("--pages", default="",
                     help="처리할 쪽 범위 (예: 1-3,7 / 비우면 전체)")
    src.add_argument("--pdf-text", choices=["auto", "always", "never"], default="auto",
                     help="PDF 안에 이미 글자가 있으면 OCR 없이 사용 (기본: auto)")
    src.add_argument("-r", "--recursive", action="store_true",
                     help="폴더를 지정했을 때 하위 폴더까지 훑기")
    src.add_argument("--all-frames", action="store_true",
                     help="움직이는 그림(GIF 등)의 모든 장면을 쪽으로 만들기 "
                          "(기본: 첫 장면만)")

    pre = parser.add_argument_group("이미지 보정")
    pre.add_argument("--no-preprocess", action="store_true", help="보정 없이 원본 그대로 인식")
    pre.add_argument("--no-deskew", action="store_true", help="기울기 자동 보정 끄기")
    pre.add_argument("--no-grayscale", action="store_true",
                     help="회색조로 바꾸지 않고 색을 그대로 두기 "
                          "(색으로 글자와 배경을 나눈 화면 캡처에 도움이 됩니다)")
    pre.add_argument("--no-auto-rotate", action="store_true", help="90/180도 회전 감지 끄기")
    pre.add_argument("--binarize", action="store_true",
                     help="흑백 이진화 (그림자·얼룩이 있는 사진에 효과적)")
    pre.add_argument("--denoise", action="store_true", help="노이즈 제거 (느려짐)")

    lay = parser.add_argument_group("문서 구성")
    lay.add_argument("--keep-line-breaks", action="store_true",
                     help="줄바꿈을 그대로 살리기 (기본은 문단으로 합침)")
    lay.add_argument("--no-headings", action="store_true", help="제목 자동 인식 끄기")
    lay.add_argument("--no-lists", action="store_true", help="목록 자동 인식 끄기")
    lay.add_argument("--no-page-break", action="store_true", help="쪽 나눔 넣지 않기")
    lay.add_argument("--embed-image", action="store_true",
                     help="원본 이미지도 문서에 함께 넣기")
    lay.add_argument("--font-korean", default="맑은 고딕", help="한글 글꼴 (기본: 맑은 고딕)")
    lay.add_argument("--font-latin", default="맑은 고딕", help="영문 글꼴")
    lay.add_argument("--font-size", type=float, default=11.0, help="본문 글자 크기 (pt)")
    lay.add_argument("--line-spacing", type=float, default=1.6, help="줄 간격 (기본: 1.6)")

    msg = parser.add_argument_group("메시지")
    msg.add_argument("-q", "--quiet", action="store_true", help="진행 상황 숨기기")
    msg.add_argument("-v", "--verbose", action="store_true", help="자세한 로그 보기")


def options_from_args(args: argparse.Namespace) -> ConvertOptions:
    formats = [f.strip().lower() for f in str(args.formats).split(",") if f.strip()]
    if not formats:
        formats = ["docx", "hwpx"]

    preprocess = PreprocessOptions(
        enabled=not args.no_preprocess,
        grayscale=not args.no_grayscale,
        deskew=not args.no_deskew,
        auto_rotate=not args.no_auto_rotate,
        binarize=args.binarize,
        denoise=args.denoise,
    )
    return ConvertOptions(
        output=args.output,
        formats=formats,
        merge=args.merge,
        overwrite=args.overwrite,
        engine=args.engine,
        language=args.language,
        psm=args.psm,
        oem=args.oem,
        ocr_timeout=args.ocr_timeout,
        tesseract_cmd=args.tesseract_cmd,
        min_confidence=args.min_confidence,
        dpi=args.dpi,
        pdf_text=args.pdf_text,
        pages=args.pages,
        recursive=args.recursive,
        all_frames=args.all_frames,
        detect_headings=not args.no_headings,
        detect_lists=not args.no_lists,
        keep_line_breaks=args.keep_line_breaks,
        page_break=not args.no_page_break,
        embed_image=args.embed_image,
        title=args.title,
        font_korean=args.font_korean,
        font_latin=args.font_latin,
        font_size=args.font_size,
        line_spacing=args.line_spacing,
        hwp_format=args.hwp_format,
        preprocess=preprocess,
        report=args.report,
        quiet=args.quiet,
        verbose=args.verbose,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 하위 명령을 생략하면 convert로 본다: `scan2doc 사진.jpg`
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "convert")

    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "command", None)

    if command is None:
        parser.print_help()
        return 0
    if command == "doctor":
        from .doctor import run_doctor

        result = run_doctor()
        print("\n".join(result.lines))
        return 0 if result.ok else 1
    if command == "formats":
        print("지원하는 출력 형식")
        for name, ext, desc in describe_writers():
            print(f"  {name:<6} {ext:<7} {desc}")
        print("\n  ※ -f hwp 로 적으면 --hwp-format 설정에 따라 hwpx 또는 hwpml로 저장됩니다.")
        return 0
    if command == "gui":
        from .gui import main as gui_main

        return gui_main()
    if command == "serve":
        return _run_serve(args)

    return _run_convert(args)


def _run_serve(args: argparse.Namespace) -> int:
    from .web.app import WebSettings
    from .web.server import serve

    settings = WebSettings.from_env()
    if args.workers is not None:
        settings.workers = max(1, args.workers)
    if args.max_upload_mb is not None:
        settings.max_upload_mb = max(1, args.max_upload_mb)
    if args.workspace is not None:
        settings.workspace = args.workspace

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        return serve(args.host, args.port, settings=settings,
                     reload=args.reload, open_browser=args.open_browser)
    except DependencyError as exc:  # FastAPI·uvicorn이 없을 때 설치 방법을 알려 준다
        print(f"오류: {exc}", file=sys.stderr)
        return 1


def _run_convert(args: argparse.Namespace) -> int:
    from .pipeline import convert

    options = options_from_args(args)
    logging.basicConfig(
        level=logging.DEBUG if options.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    def progress(stage: str, message: str, ratio: float) -> None:
        if not options.quiet:
            print(f"  … {message}", file=sys.stderr, flush=True)

    try:
        results = convert(args.inputs, options, progress=progress)
    except Scan2DocError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130

    if not options.quiet:
        _print_summary(results)
    return 0


def _print_summary(results) -> None:
    total_pages = sum(r.page_count for r in results)
    print(f"\n변환 완료: 파일 {len(results)}개 · 총 {total_pages}쪽")
    for result in results:
        confidence = result.confidence
        conf_text = f"{confidence:.0f}%" if confidence >= 0 else "-"
        detail = f"{result.page_count}쪽, 인식 신뢰도 {conf_text}, {result.elapsed:.1f}초"
        if result.text_layer_pages:
            detail += f", PDF 텍스트 {result.text_layer_pages}쪽"
        print(f"  · {detail}")
        for path in result.outputs:
            print(f"      → {path}")
        if 0 <= confidence < 70:
            print("      ⚠️  인식률이 낮습니다. --binarize 를 켜거나 더 선명한 사진으로 "
                  "다시 시도해 보세요.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

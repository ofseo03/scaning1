"""명령줄 인자 처리."""

from __future__ import annotations

from pathlib import Path

import pytest

from scan2doc.cli import build_parser, main, options_from_args


def parse(argv):
    return build_parser().parse_args(argv)


class TestParser:
    def test_하위명령_없이_파일만_줘도_변환으로_본다(self, capsys):
        # main()이 'convert'를 끼워 넣는지 확인한다.
        code = main(["없는파일.jpg"])
        assert code == 1
        assert "오류" in capsys.readouterr().err

    def test_기본_출력은_docx와_hwpx(self):
        options = options_from_args(parse(["convert", "a.jpg"]))
        assert options.formats == ["docx", "hwpx"]

    def test_형식을_쉼표로_나눈다(self):
        options = options_from_args(parse(["convert", "a.jpg", "-f", "docx, txt ,MD"]))
        assert options.formats == ["docx", "txt", "md"]

    def test_기본_언어는_한국어와_영어(self):
        assert options_from_args(parse(["convert", "a.jpg"])).language == "kor+eng"

    def test_psm은_기본이_auto다(self):
        assert options_from_args(parse(["convert", "a.jpg"])).psm == "auto"

    def test_psm에_숫자를_줄_수_있다(self):
        assert options_from_args(parse(["convert", "a.jpg", "--psm", "6"])).psm == 6

    @pytest.mark.parametrize("bad", ["99", "여섯"])
    def test_잘못된_psm은_거부한다(self, bad):
        with pytest.raises(SystemExit):
            parse(["convert", "a.jpg", "--psm", bad])

    def test_보정_끄기_옵션이_전달된다(self):
        options = options_from_args(parse([
            "convert", "a.jpg", "--no-preprocess", "--no-deskew", "--binarize",
        ]))
        assert options.preprocess.enabled is False
        assert options.preprocess.deskew is False
        assert options.preprocess.binarize is True

    def test_문서_구성_옵션이_전달된다(self):
        options = options_from_args(parse([
            "convert", "a.jpg", "--no-headings", "--no-lists", "--keep-line-breaks",
            "--no-page-break", "--font-size", "13", "--font-korean", "함초롬바탕",
        ]))
        assert (options.detect_headings, options.detect_lists) == (False, False)
        assert options.keep_line_breaks is True
        assert options.page_break is False
        assert options.font_size == 13
        assert options.font_korean == "함초롬바탕"

    def test_출력_경로는_Path로_바뀐다(self):
        options = options_from_args(parse(["convert", "a.jpg", "-o", "결과/"]))
        assert options.output == Path("결과/")


class TestSubcommands:
    def test_formats는_형식_목록을_찍는다(self, capsys):
        assert main(["formats"]) == 0
        out = capsys.readouterr().out
        assert "hwpx" in out and "docx" in out

    def test_인자가_없으면_도움말(self, capsys):
        assert main([]) == 0
        assert "scan2doc" in capsys.readouterr().out

    def test_doctor는_점검_결과를_찍는다(self, capsys):
        code = main(["doctor"])
        assert code in (0, 1)
        assert "환경 점검" in capsys.readouterr().out

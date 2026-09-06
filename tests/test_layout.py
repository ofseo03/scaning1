"""OCR 낱말을 문단으로 되살리는 규칙."""

from __future__ import annotations

import pytest

from scan2doc.config import ConvertOptions
from scan2doc.layout import WordRecord, build_blocks, split_list_marker
from scan2doc.model import BBox, BlockKind


def rec(text, *, block=1, par=1, line=1, x=0, y=0, height=24, width=None, line_text=None):
    return WordRecord(
        text=text,
        bbox=BBox(x, y, width if width is not None else len(text) * height, height),
        confidence=90,
        block_num=block,
        par_num=par,
        line_num=line,
        line_text=line_text,
    )


@pytest.fixture
def options():
    return ConvertOptions()


class TestSplitListMarker:
    @pytest.mark.parametrize("text,marker,rest,ordered", [
        ("- 첫째 항목", "-", "첫째 항목", False),
        ("• 점 항목", "•", "점 항목", False),
        ("1. 번호 항목", "1.", "번호 항목", True),
        ("(3) 괄호 번호", "(3)", "괄호 번호", True),
        ("가. 한글 번호", "가.", "한글 번호", True),
        ("① 동그라미", "①", "동그라미", True),
    ])
    def test_기호를_떼어낸다(self, text, marker, rest, ordered):
        assert split_list_marker(text) == (marker, rest, ordered)

    @pytest.mark.parametrize("text", ["보통 문장입니다", "2024년 실적", "-붙어있음", "1.5배 증가"])
    def test_목록이_아니면_None(self, text):
        assert split_list_marker(text) is None


class TestBuildBlocks:
    def test_같은_문단의_줄을_하나로_합친다(self, options):
        records = [
            rec("문서 관리에 관한", line=1),
            rec("기본적인 사항을", line=2, y=40),
        ]
        blocks = build_blocks(records, options)
        assert len(blocks) == 1
        assert blocks[0].text == "문서 관리에 관한 기본적인 사항을"

    def test_문단_번호가_다르면_나눈다(self, options):
        blocks = build_blocks([rec("첫 문단", par=1), rec("둘째 문단", par=2, y=60)], options)
        assert [b.text for b in blocks] == ["첫 문단", "둘째 문단"]

    def test_큰_글자는_제목으로_본다(self, options):
        records = [
            rec("제1장 총칙", block=1, height=48),
            rec("보통 크기의 본문입니다", block=2, height=24, y=80),
            rec("역시 보통 크기 본문", block=3, height=24, y=120),
            rec("세 번째 보통 본문", block=4, height=24, y=160),
        ]
        blocks = build_blocks(records, options)
        assert blocks[0].kind is BlockKind.HEADING
        assert blocks[0].level == 1
        assert all(b.kind is BlockKind.PARAGRAPH for b in blocks[1:])

    def test_제목_인식을_끌_수_있다(self):
        options = ConvertOptions(detect_headings=False)
        records = [
            rec("아주 큰 제목", height=60),
            rec("본문 하나", height=24, y=100, block=2),
            rec("본문 둘", height=24, y=140, block=3),
            rec("본문 셋", height=24, y=180, block=4),
        ]
        assert all(b.kind is BlockKind.PARAGRAPH for b in build_blocks(records, options))

    def test_한_문단에_묶인_목록을_항목별로_끊는다(self, options):
        # OCR은 연속한 목록 줄을 한 문단으로 묶어 놓는 일이 잦다.
        records = [
            rec("- 첫째, 모든 문서는 보관한다.", line=1),
            rec("- 둘째, 기간은 5년이다.", line=2, y=40),
        ]
        blocks = build_blocks(records, options)
        assert len(blocks) == 2
        assert all(b.kind is BlockKind.LIST_ITEM for b in blocks)
        assert blocks[0].text == "첫째, 모든 문서는 보관한다."
        assert blocks[0].list_marker == "-"
        assert blocks[1].ordered is False

    def test_번호_목록은_ordered로_표시한다(self, options):
        blocks = build_blocks([rec("1. 첫째 항목")], options)
        assert blocks[0].kind is BlockKind.LIST_ITEM
        assert blocks[0].ordered is True

    def test_줄바꿈_보존_모드에서는_줄마다_문단이_된다(self):
        options = ConvertOptions(keep_line_breaks=True)
        records = [rec("첫 줄", line=1), rec("둘째 줄", line=2, y=40)]
        assert [b.text for b in build_blocks(records, options)] == ["첫 줄", "둘째 줄"]

    def test_엔진이_준_줄_문장을_쓴다(self, options):
        records = [
            rec("규", x=0, width=20, line_text="규정은 회사의"),
            rec("정", x=20, width=20, line_text="규정은 회사의"),
        ]
        assert build_blocks(records, options)[0].text == "규정은 회사의"

    def test_빈_입력은_빈_목록(self, options):
        assert build_blocks([], options) == []

    def test_공백뿐인_낱말은_버린다(self, options):
        assert build_blocks([rec("   ")], options) == []

"""문서 모델과 텍스트 이어붙이기 규칙."""

from __future__ import annotations

import json

import pytest

from scan2doc.model import (
    BBox,
    Block,
    BlockKind,
    Document,
    Line,
    Page,
    Word,
    is_hangul,
    join_lines,
    join_words,
)


def word(text: str, x: int, width: int, *, y: int = 0, height: int = 24) -> Word:
    return Word(text=text, bbox=BBox(x, y, width, height), confidence=90)


class TestJoinLines:
    def test_한국어는_줄이_바뀌어도_띄어쓴다(self):
        # 한글 문서는 어절 경계에서 줄이 바뀌므로 붙이면 안 된다.
        assert join_lines(["문서 관리에 관한", "기본적인 사항을"]) == "문서 관리에 관한 기본적인 사항을"

    def test_영문_분철은_다시_붙인다(self):
        assert join_lines(["inter-", "national"]) == "international"

    def test_한자는_붙여쓴다(self):
        assert join_lines(["漢字文書", "管理規程"]) == "漢字文書管理規程"

    def test_빈_줄은_무시한다(self):
        assert join_lines(["첫 줄", "", "  ", "둘째 줄"]) == "첫 줄 둘째 줄"

    def test_빈_입력은_빈_문자열(self):
        assert join_lines([]) == ""


class TestJoinWords:
    def test_간격이_좁은_한글_음절은_한_어절로_붙인다(self):
        # OCR이 '규','정','은' 으로 쪼갠 것을 '규정은'으로 되돌린다.
        words = [word("규", 0, 20), word("정", 22, 20), word("은", 44, 20)]
        assert join_words(words) == "규정은"

    def test_간격이_넓으면_띄어쓴다(self):
        # 글자 높이 24 → 기준 약 10px. 20px 간격은 띄어쓰기다.
        words = [word("문서", 0, 40), word("관리", 60, 40)]
        assert join_words(words) == "문서 관리"

    def test_라틴_낱말은_간격과_무관하게_띄어쓴다(self):
        words = [word("Hello", 0, 50), word("world", 52, 50)]
        assert join_words(words) == "Hello world"

    def test_겹친_상자도_붙여쓴다(self):
        # 받침이 큰 글자는 앞 글자와 상자가 겹쳐 간격이 음수가 되기도 한다.
        words = [word("제", 0, 40), word("1", 20, 20), word("조", 38, 20)]
        assert join_words(words) == "제1조"

    def test_빈_낱말만_있으면_빈_문자열(self):
        assert join_words([word("  ", 0, 10)]) == ""


class TestBBox:
    def test_여러_상자를_감싸는_상자(self):
        merged = BBox.union([BBox(10, 20, 30, 40), BBox(5, 25, 10, 10)])
        assert (merged.x, merged.y, merged.right, merged.bottom) == (5, 20, 40, 60)

    def test_빈_목록은_영_상자(self):
        assert BBox.union([]) == BBox(0, 0, 0, 0)


class TestLineAndBlock:
    def test_엔진이_준_문장을_그대로_쓴다(self):
        line = Line(words=[word("가", 0, 20), word("나", 22, 20)], raw_text="가 나")
        assert line.text == "가 나"

    def test_줄_높이는_중앙값(self):
        line = Line(words=[word("가", 0, 20, height=20),
                           word("나", 30, 20, height=24),
                           word("다", 60, 20, height=90)])
        assert line.height == 24

    def test_신뢰도는_평균(self):
        line = Line(words=[Word("가", BBox(0, 0, 10, 10), 80),
                           Word("나", BBox(20, 0, 10, 10), 100)])
        assert line.confidence == 90

    def test_덮어쓴_본문이_우선한다(self):
        block = Block(lines=[Line(words=[word("무시", 0, 20)])], text_override="진짜 본문")
        assert block.text == "진짜 본문"

    def test_빈_블록_판정(self):
        assert Block(text_override="   ").is_empty()


class TestDocument:
    def test_JSON_직렬화에_본문이_들어간다(self):
        doc = Document(
            title="시험",
            pages=[Page(index=0, blocks=[
                Block(kind=BlockKind.HEADING, level=1, text_override="머리말"),
            ])],
        )
        data = json.loads(doc.to_json())
        block = data["pages"][0]["blocks"][0]
        assert block["kind"] == "heading"
        assert block["text"] == "머리말"

    def test_전체_본문은_쪽을_이어붙인다(self):
        doc = Document(pages=[
            Page(index=0, blocks=[Block(text_override="첫 쪽")]),
            Page(index=1, blocks=[Block(text_override="둘째 쪽")]),
        ])
        assert doc.text == "첫 쪽\n\n둘째 쪽"


@pytest.mark.parametrize("ch,expected", [("가", True), ("ㄱ", True), ("漢", False), ("A", False)])
def test_한글_판정(ch, expected):
    assert is_hangul(ch) is expected

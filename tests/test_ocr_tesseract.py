"""Tesseract 출력 해석 (엔진 실행 없이 순수 함수만 확인)."""

from __future__ import annotations

import pytest

from scan2doc.ocr.tesseract import (
    _attach_line_text,
    _psm_candidates,
    _score,
    records_from_tsv,
)
from scan2doc.ocr.base import OcrResult

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


def word_row(text, *, level=5, block=1, par=1, line=1, left=0, top=0,
             width=20, height=24, conf=95.0):
    return "\t".join(str(v) for v in
                     [level, 1, block, par, line, 1, left, top, width, height, conf, text])


class TestRecordsFromTsv:
    def test_낱말_행만_읽는다(self):
        text = tsv(word_row("", level=4), word_row("규정"), word_row("", level=1))
        records = records_from_tsv(text)
        assert [r.text for r in records] == ["규정"]

    def test_좌표와_신뢰도를_읽는다(self):
        record = records_from_tsv(tsv(word_row("가", left=10, top=20, width=30, height=40,
                                               conf=88.5)))[0]
        assert (record.bbox.x, record.bbox.y, record.bbox.width, record.bbox.height) == (10, 20, 30, 40)
        assert record.confidence == 88.5

    def test_빈_글자는_버린다(self):
        assert records_from_tsv(tsv(word_row("   "))) == []

    def test_신뢰도_기준_아래는_버린다(self):
        text = tsv(word_row("좋음", conf=90), word_row("나쁨", conf=30))
        assert [r.text for r in records_from_tsv(text, min_confidence=50)] == ["좋음"]

    def test_신뢰도가_없으면_버리지_않는다(self):
        # conf가 -1인 행은 신뢰도 정보 없음을 뜻하므로 걸러 내지 않는다.
        assert len(records_from_tsv(tsv(word_row("가", conf=-1)), min_confidence=50)) == 1

    def test_빈_출력은_빈_목록(self):
        assert records_from_tsv("") == []

    def test_형식이_다르면_조용히_포기한다(self):
        assert records_from_tsv("완전히\t다른\t형식\nA\tB\tC") == []

    def test_숫자가_아닌_행은_건너뛴다(self):
        broken = "\t".join(["5", "1", "1", "1", "1", "1", "x", "0", "20", "24", "95", "가"])
        assert records_from_tsv(tsv(broken, word_row("나"))) == records_from_tsv(tsv(word_row("나")))


class TestAttachLineText:
    def test_줄_수가_맞으면_문장을_붙인다(self):
        records = records_from_tsv(tsv(
            word_row("규", line=1), word_row("정", line=1), word_row("나중", line=2),
        ))
        _attach_line_text(records, "규정은 회사의\n나중 줄입니다\n")
        assert records[0].line_text == "규정은 회사의"
        assert records[2].line_text == "나중 줄입니다"

    def test_줄_수가_다르면_붙이지_않는다(self):
        # 잘못 짝지은 문장을 쓰느니 좌표 기반 이어붙이기로 되돌아간다.
        records = records_from_tsv(tsv(word_row("가", line=1), word_row("나", line=2)))
        _attach_line_text(records, "한 줄뿐입니다\n")
        assert all(r.line_text is None for r in records)

    def test_빈_텍스트는_무시한다(self):
        records = records_from_tsv(tsv(word_row("가")))
        _attach_line_text(records, "   ")
        assert records[0].line_text is None


class TestPsmSelection:
    def test_auto는_후보를_순서대로_돌려준다(self):
        assert _psm_candidates("auto") == (4, 3)

    @pytest.mark.parametrize("value", [4, "6"])
    def test_숫자를_주면_그것만_쓴다(self, value):
        assert _psm_candidates(value) == (int(value),)

    def test_점수는_글자_수와_신뢰도를_함께_본다(self):
        many = OcrResult(records=records_from_tsv(tsv(word_row("길고 좋은 결과", conf=95))))
        few = OcrResult(records=records_from_tsv(tsv(word_row("짧음", conf=95))))
        assert _score(many) > _score(few)

    def test_신뢰도가_낮으면_점수도_낮다(self):
        good = OcrResult(records=records_from_tsv(tsv(word_row("같은 길이", conf=95))))
        bad = OcrResult(records=records_from_tsv(tsv(word_row("같은 길이", conf=20))))
        assert _score(good) > _score(bad)

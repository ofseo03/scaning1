"""변환 흐름 전체 (OCR 엔진은 가짜로 대체)."""

from __future__ import annotations

import shutil

import pytest
from PIL import Image

from scan2doc import ocr
from scan2doc.config import ConvertOptions, PreprocessOptions
from scan2doc.errors import InputError
from scan2doc.layout import WordRecord
from scan2doc.model import BBox
from scan2doc.ocr.base import OcrEngine, OcrResult
from scan2doc.pipeline import convert


class StubEngine(OcrEngine):
    """실제 OCR 없이 정해진 문장을 돌려주는 시험용 엔진."""

    name = "stub"
    description = "테스트용"
    text = "제1장 총칙"

    def check(self, options=None) -> None:
        return None

    def recognize(self, image, options) -> OcrResult:
        records = [
            WordRecord(
                text=piece,
                bbox=BBox(x=index * 100, y=0, width=70, height=24),
                confidence=95.0,
                block_num=1,
                par_num=1,
                line_num=1,
            )
            for index, piece in enumerate(self.text.split())
        ]
        return OcrResult(records=records, engine=self.name)


@pytest.fixture(autouse=True)
def stub_engine():
    ocr.register(StubEngine)
    yield
    ocr._ENGINES.pop("stub", None)


@pytest.fixture
def options():
    # 가짜 엔진은 회전 감지를 지원하지 않으므로 보정은 최소한만 켠다.
    return ConvertOptions(
        engine="stub",
        formats=["txt"],
        preprocess=PreprocessOptions(deskew=False, auto_rotate=False),
    )


def make_image(path, size=(1200, 400)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)
    return path


class TestOutputPaths:
    def test_출력을_지정하지_않으면_원본_옆에_저장한다(self, tmp_path, options):
        source = make_image(tmp_path / "사진.png")
        result = convert([source], options)[0]
        assert result.outputs == [tmp_path / "사진.txt"]

    def test_폴더를_주면_그_안에_저장한다(self, tmp_path, options):
        source = make_image(tmp_path / "사진.png")
        options.output = tmp_path / "결과"
        result = convert([source], options)[0]
        assert result.outputs == [tmp_path / "결과" / "사진.txt"]
        assert result.outputs[0].exists()

    def test_파일_이름을_주면_그_이름으로_저장한다(self, tmp_path, options):
        source = make_image(tmp_path / "사진.png")
        options.output = tmp_path / "보고서.txt"
        assert convert([source], options)[0].outputs == [tmp_path / "보고서.txt"]

    def test_같은_이름이_있으면_번호를_붙인다(self, tmp_path, options):
        source = make_image(tmp_path / "사진.png")
        (tmp_path / "사진.txt").write_text("먼저 있던 파일")
        result = convert([source], options)[0]
        assert result.outputs == [tmp_path / "사진 (1).txt"]
        assert (tmp_path / "사진.txt").read_text() == "먼저 있던 파일"

    def test_overwrite면_덮어쓴다(self, tmp_path, options):
        source = make_image(tmp_path / "사진.png")
        (tmp_path / "사진.txt").write_text("먼저 있던 파일")
        options.overwrite = True
        result = convert([source], options)[0]
        assert result.outputs == [tmp_path / "사진.txt"]
        assert "총칙" in (tmp_path / "사진.txt").read_text(encoding="utf-8")


class TestConversion:
    def test_인식_결과가_문서에_담긴다(self, tmp_path, options):
        result = convert([make_image(tmp_path / "a.png")], options)[0]
        assert result.page_count == 1
        assert result.confidence == 95.0
        assert "제1장 총칙" in result.document.text

    def test_입력마다_문서를_하나씩_만든다(self, tmp_path, options):
        make_image(tmp_path / "a.png")
        make_image(tmp_path / "b.png")
        results = convert([tmp_path], options)
        assert len(results) == 2

    def test_merge면_문서_하나로_합친다(self, tmp_path, options):
        make_image(tmp_path / "a.png")
        make_image(tmp_path / "b.png")
        options.merge = True
        results = convert([tmp_path], options)
        assert len(results) == 1
        assert results[0].page_count == 2

    def test_여러_형식을_한꺼번에_저장한다(self, tmp_path, options):
        options.formats = ["txt", "md", "hwpx", "hwpml"]
        outputs = convert([make_image(tmp_path / "a.png")], options)[0].outputs
        assert [p.suffix for p in outputs] == [".txt", ".md", ".hwpx", ".hwpml"]
        assert all(p.exists() for p in outputs)

    def test_report를_함께_저장한다(self, tmp_path, options):
        options.report = tmp_path / "결과.json"
        convert([make_image(tmp_path / "a.png")], options)
        assert "제1장" in options.report.read_text(encoding="utf-8")

    def test_진행_상황을_알려준다(self, tmp_path, options):
        seen = []
        convert([make_image(tmp_path / "a.png")], options,
                progress=lambda stage, message, ratio: seen.append(stage))
        assert "page" in seen and "write" in seen

    def test_진행_콜백이_실패해도_변환은_끝난다(self, tmp_path, options):
        def broken(stage, message, ratio):
            raise RuntimeError("콜백 오류")

        result = convert([make_image(tmp_path / "a.png")], options, progress=broken)[0]
        assert result.outputs[0].exists()

    def test_없는_입력은_오류(self, tmp_path, options):
        with pytest.raises(InputError):
            convert([tmp_path / "없음.png"], options)

    def test_원본_이미지를_문서에_넣을_수_있다(self, tmp_path, options):
        options.embed_image = True
        options.formats = ["docx"]
        result = convert([make_image(tmp_path / "a.png")], options)[0]
        assert result.outputs[0].exists()
        assert result.document.pages[0].image_path is not None


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract 없음")
class TestEndToEnd:
    """실제 Tesseract로 한국어 이미지를 변환한다."""

    @pytest.fixture
    def scan(self, tmp_path):
        from fixtures import find_korean_font, make_sample_image

        if find_korean_font() is None:
            pytest.skip("한국어 글꼴 없음")
        return make_sample_image(tmp_path / "scan.png", rotate=1.5)

    def test_한국어_문서를_읽어_모든_형식으로_저장한다(self, scan, tmp_path):
        options = ConvertOptions(
            formats=["docx", "hwpx", "txt"],
            output=tmp_path / "결과",
            language="kor+eng",
        )
        result = convert([scan], options)[0]
        text = result.document.text

        assert result.confidence > 70, f"인식률이 너무 낮습니다: {text}"
        assert "총칙" in text
        assert "규정" in text
        assert all(path.exists() and path.stat().st_size > 0 for path in result.outputs)

    def test_기울어진_사진도_바로잡아_읽는다(self, tmp_path):
        from fixtures import find_korean_font, make_sample_image

        if find_korean_font() is None:
            pytest.skip("한국어 글꼴 없음")
        scan = make_sample_image(tmp_path / "tilted.png", rotate=4.0)
        options = ConvertOptions(formats=["txt"], output=tmp_path / "결과")
        result = convert([scan], options)[0]
        assert "총칙" in result.document.text

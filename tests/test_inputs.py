"""입력 수집과 페이지 적재."""

from __future__ import annotations

import pytest
from PIL import Image

from scan2doc.config import ConvertOptions, parse_page_range
from scan2doc.errors import InputError
from scan2doc.inputs import collect_inputs, load_pages


def make_image(path, size=(200, 100)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)
    return path


class TestParsePageRange:
    @pytest.mark.parametrize("spec,total,expected", [
        ("", 3, [1, 2, 3]),
        ("2", 5, [2]),
        ("1-3", 5, [1, 2, 3]),
        ("1-2,5", 6, [1, 2, 5]),
        ("3-", 5, [3, 4, 5]),
        ("-2", 5, [1, 2]),
        ("3-1", 5, [1, 2, 3]),      # 거꾸로 적어도 받아준다
        ("2,2,2", 5, [2]),          # 중복 제거
        ("1-99", 3, [1, 2, 3]),     # 전체 쪽 수로 자른다
    ])
    def test_범위를_쪽_번호로_바꾼다(self, spec, total, expected):
        assert parse_page_range(spec, total) == expected


class TestCollectInputs:
    def test_숫자를_사람처럼_정렬한다(self, tmp_path):
        for name in ("page10.png", "page2.png", "page1.png"):
            make_image(tmp_path / name)
        names = [p.name for p in collect_inputs([tmp_path])]
        assert names == ["page1.png", "page2.png", "page10.png"]

    def test_지원하지_않는_확장자는_오류(self, tmp_path):
        target = tmp_path / "메모.txt"
        target.write_text("hello")
        with pytest.raises(InputError, match="지원하지 않는 형식"):
            collect_inputs([target])

    def test_폴더_안의_지원하지_않는_파일은_건너뛴다(self, tmp_path):
        make_image(tmp_path / "a.png")
        (tmp_path / "메모.txt").write_text("hello")
        assert [p.name for p in collect_inputs([tmp_path])] == ["a.png"]

    def test_하위_폴더는_recursive일_때만_본다(self, tmp_path):
        make_image(tmp_path / "a.png")
        make_image(tmp_path / "안쪽" / "b.png")
        assert len(collect_inputs([tmp_path])) == 1
        assert len(collect_inputs([tmp_path], recursive=True)) == 2

    def test_같은_파일을_두_번_넣어도_한_번만(self, tmp_path):
        path = make_image(tmp_path / "a.png")
        assert len(collect_inputs([path, path])) == 1

    def test_없는_파일은_오류(self, tmp_path):
        with pytest.raises(InputError, match="찾을 수 없습니다"):
            collect_inputs([tmp_path / "없는파일.png"])

    def test_빈_폴더는_오류(self, tmp_path):
        with pytest.raises(InputError, match="찾지 못했습니다"):
            collect_inputs([tmp_path])


class TestLoadPages:
    def test_이미지_한_장은_한_쪽(self, tmp_path):
        path = make_image(tmp_path / "a.png", size=(300, 200))
        pages = list(load_pages(path, ConvertOptions()))
        assert len(pages) == 1
        assert pages[0].needs_ocr
        assert (pages[0].width, pages[0].height) == (300, 200)

    def test_여러_장_TIFF는_쪽마다_나눈다(self, tmp_path):
        path = tmp_path / "multi.tiff"
        frames = [Image.new("RGB", (100, 80), "white") for _ in range(3)]
        frames[0].save(path, save_all=True, append_images=frames[1:])
        assert len(list(load_pages(path, ConvertOptions()))) == 3

    def test_쪽_범위를_적용한다(self, tmp_path):
        path = tmp_path / "multi.tiff"
        frames = [Image.new("RGB", (100, 80), "white") for _ in range(4)]
        frames[0].save(path, save_all=True, append_images=frames[1:])
        pages = list(load_pages(path, ConvertOptions(pages="2-3")))
        assert [p.page_no for p in pages] == [2, 3]

    def test_손상된_이미지는_오류(self, tmp_path):
        path = tmp_path / "broken.png"
        path.write_bytes(b"not really a png")
        with pytest.raises(InputError, match="열 수 없습니다"):
            list(load_pages(path, ConvertOptions()))

    def test_내려받다_만_이미지는_안내_메시지(self, tmp_path):
        # 헤더는 멀쩡하고 뒤가 잘린 파일. 브라우저에서 저장하다 끊기면 이렇게 된다.
        whole = tmp_path / "whole.png"
        make_image(whole, size=(400, 300))
        path = tmp_path / "cut.png"
        path.write_bytes(whole.read_bytes()[:120])
        with pytest.raises(InputError, match="손상"):
            list(load_pages(path, ConvertOptions()))


def make_animation(path, frames=5, size=(200, 120)):
    """움직이는 GIF(화면 녹화·데모 영상)를 흉내 낸다."""
    images = [Image.new("RGB", size, color) for color in
              ("white", "gray", "white", "gray", "white")[:frames]]
    images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)
    return path


class TestAnimation:
    def test_움직이는_그림은_첫_장면만_쓴다(self, tmp_path):
        path = make_animation(tmp_path / "demo.gif", frames=5)
        pages = list(load_pages(path, ConvertOptions()))
        assert len(pages) == 1

    def test_all_frames면_모든_장면을_쓴다(self, tmp_path):
        path = make_animation(tmp_path / "demo.gif", frames=5)
        pages = list(load_pages(path, ConvertOptions(all_frames=True)))
        assert len(pages) == 5

    def test_쪽_범위를_주면_장면을_쪽으로_본다(self, tmp_path):
        path = make_animation(tmp_path / "demo.gif", frames=5)
        pages = list(load_pages(path, ConvertOptions(pages="2-3")))
        assert [p.page_no for p in pages] == [2, 3]

    def test_여러_장_TIFF는_영향을_받지_않는다(self, tmp_path):
        # 여러 장이 담긴 TIFF는 진짜 여러 쪽이므로 그대로 모두 쓴다.
        path = tmp_path / "multi.tiff"
        frames = [Image.new("RGB", (100, 80), "white") for _ in range(3)]
        frames[0].save(path, save_all=True, append_images=frames[1:])
        assert len(list(load_pages(path, ConvertOptions()))) == 3


class TestSniffKind:
    def test_확장자가_없어도_이미지면_받는다(self, tmp_path):
        # 브라우저에서 '이미지 저장'을 하면 확장자 없이 저장되는 일이 흔하다.
        path = tmp_path / "screenshot"
        Image.new("RGB", (300, 200), "white").save(path, "PNG")
        assert [p.name for p in collect_inputs([path])] == ["screenshot"]
        assert len(list(load_pages(path, ConvertOptions()))) == 1

    def test_낯선_확장자도_내용으로_판별한다(self, tmp_path):
        path = tmp_path / "capture.jfif"
        Image.new("RGB", (300, 200), "white").save(path, "JPEG")
        assert len(list(load_pages(path, ConvertOptions()))) == 1

    def test_이미지도_PDF도_아니면_여전히_오류(self, tmp_path):
        path = tmp_path / "메모"
        path.write_text("그냥 글")
        with pytest.raises(InputError, match="지원하지 않는 형식"):
            collect_inputs([path])


class TestPdf:
    @pytest.fixture
    def pdf(self, tmp_path):
        from fixtures import make_sample_pdf

        path = make_sample_pdf(tmp_path / "digital.pdf", pages=2)
        if path is None:
            pytest.skip("pymupdf 없음")
        return path

    def test_텍스트_레이어가_있으면_OCR을_건너뛴다(self, pdf):
        pages = list(load_pages(pdf, ConvertOptions()))
        assert len(pages) == 2
        assert all(not p.needs_ocr for p in pages)
        assert any("시험" in b.text or "text layer" in b.text.lower()
                   for b in pages[0].native_blocks)

    def test_never로_두면_항상_OCR로_보낸다(self, pdf):
        pages = list(load_pages(pdf, ConvertOptions(pdf_text="never", dpi=72)))
        assert all(p.needs_ocr and p.image is not None for p in pages)

    def test_dpi에_따라_렌더링_크기가_달라진다(self, pdf):
        low = list(load_pages(pdf, ConvertOptions(pdf_text="never", dpi=72)))[0]
        high = list(load_pages(pdf, ConvertOptions(pdf_text="never", dpi=144)))[0]
        assert high.width > low.width

    def test_망가진_PDF는_오류(self, tmp_path):
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"%PDF-1.4 broken")
        with pytest.raises(InputError):
            list(load_pages(path, ConvertOptions()))

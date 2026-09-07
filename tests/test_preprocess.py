"""OCR 앞단 이미지 보정."""

from __future__ import annotations

from PIL import Image

from scan2doc.config import PreprocessOptions
from scan2doc.preprocess import flatten_alpha, has_alpha, preprocess


def transparent_shot(size=(1200, 400)) -> Image.Image:
    """투명한 배경에 검은 글자가 놓인 화면 캡처를 흉내 낸다.

    창 모서리가 둥근 macOS 캡처나 그림자를 살린 PNG가 실제로 이런 모양이다.
    """
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(100, 400):
        for y in range(100, 140):
            image.putpixel((x, y), (0, 0, 0, 255))   # 불투명한 검은 글자
    return image


class TestAlpha:
    def test_투명도가_있는지_알아본다(self):
        assert has_alpha(transparent_shot())
        assert not has_alpha(Image.new("RGB", (10, 10), "white"))

    def test_투명한_곳은_흰색이_된다(self):
        flat = flatten_alpha(transparent_shot())
        assert flat.mode == "RGB"
        assert flat.getpixel((5, 5)) == (255, 255, 255)     # 배경
        assert flat.getpixel((200, 120)) == (0, 0, 0)       # 글자는 그대로

    def test_보정_중에도_투명한_곳이_검어지지_않는다(self):
        # 그냥 convert("RGB")로 바꾸면 여기가 검은색이 되어 글자가 묻힌다.
        result = preprocess(transparent_shot(), PreprocessOptions())
        assert result.image.getpixel((5, 5)) > 200
        assert "flatten-alpha" in result.steps

    def test_보정을_꺼도_투명도는_처리한다(self):
        result = preprocess(transparent_shot(), PreprocessOptions(enabled=False))
        assert result.image.mode == "RGB"
        assert result.image.getpixel((5, 5)) == (255, 255, 255)

    def test_투명도가_없으면_건드리지_않는다(self):
        result = preprocess(Image.new("RGB", (1200, 400), "white"),
                            PreprocessOptions(enabled=False))
        assert "flatten-alpha" not in result.steps


class TestGrayscale:
    def color_shot(self):
        return Image.new("RGB", (1200, 400), (200, 40, 40))

    def test_기본은_회색조로_바꾼다(self):
        result = preprocess(self.color_shot(), PreprocessOptions(deskew=False))
        assert result.image.mode == "L"
        assert "grayscale" in result.steps

    def test_끄면_색을_그대로_둔다(self):
        # 색으로 글자와 배경을 나눈 화면은 밝기만 남기면 글자가 묻힌다.
        result = preprocess(self.color_shot(),
                            PreprocessOptions(grayscale=False, deskew=False))
        assert result.image.mode == "RGB"
        assert "grayscale" not in result.steps

    def test_이진화를_켜면_회색조가_필요하다(self):
        result = preprocess(self.color_shot(),
                            PreprocessOptions(grayscale=False, binarize=True, deskew=False))
        assert result.image.mode == "L"


class TestUpscale:
    def test_작은_그림은_확대한다(self):
        options = PreprocessOptions(deskew=False)
        result = preprocess(Image.new("RGB", (400, 200), "white"), options)
        assert result.image.width >= options.upscale_min_width

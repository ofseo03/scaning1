"""출력 형식별 작성기."""

from __future__ import annotations

import zipfile
from xml.etree import ElementTree as ET

import pytest

from scan2doc.config import ConvertOptions
from scan2doc.errors import Scan2DocError
from scan2doc.model import Block, BlockKind, Document, Page
from scan2doc.writers import available_writers, get_writer
from scan2doc.writers.hwpx_writer import MIMETYPE


@pytest.fixture
def document():
    return Document(
        title="문서 관리 규정",
        pages=[
            Page(index=0, blocks=[
                Block(kind=BlockKind.HEADING, level=1, text_override="제1장 <총칙>"),
                Block(text_override="이 규정은 회사의 문서 관리에 & 관한 사항을 정한다."),
                Block(kind=BlockKind.LIST_ITEM, list_marker="-", text_override="전자 보관"),
                Block(kind=BlockKind.LIST_ITEM, list_marker="1.", ordered=True,
                      text_override="보존 5년"),
            ]),
            Page(index=1, blocks=[Block(text_override="둘째 쪽 내용")]),
        ],
    )


@pytest.fixture
def options():
    return ConvertOptions()


class TestRegistry:
    def test_기본_형식이_모두_등록돼_있다(self):
        assert set(available_writers()) == {"docx", "hwpx", "hwpml", "txt", "md"}

    def test_hwp는_hwpx로_안내한다(self):
        assert get_writer("hwp").name == "hwpx"

    def test_점이_붙어도_받아준다(self):
        assert get_writer(".docx").name == "docx"

    def test_모르는_형식은_오류(self):
        with pytest.raises(Scan2DocError, match="알 수 없는 출력 형식"):
            get_writer("pages")


class TestHwpx:
    @pytest.fixture
    def archive(self, document, options, tmp_path):
        path = get_writer("hwpx").write(document, tmp_path / "결과.hwpx", options)
        with zipfile.ZipFile(path) as zf:
            yield zf

    def test_mimetype이_맨_앞에_압축_없이_들어간다(self, archive):
        # OWPML(및 ODF 계열)의 요구 사항이다.
        first = archive.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype").decode() == MIMETYPE

    def test_필수_구성_파일이_모두_있다(self, archive):
        names = set(archive.namelist())
        assert {
            "version.xml",
            "META-INF/container.xml",
            "META-INF/manifest.xml",
            "Contents/content.hpf",
            "Contents/header.xml",
            "Contents/section0.xml",
        } <= names

    def test_모든_XML이_올바른_형식이다(self, archive):
        for name in archive.namelist():
            if name.endswith((".xml", ".hpf", ".rdf")):
                ET.fromstring(archive.read(name))  # 예외가 없으면 통과

    def test_본문이_들어가고_특수문자가_이스케이프된다(self, archive):
        section = archive.read("Contents/section0.xml").decode("utf-8")
        assert "제1장 &lt;총칙&gt;" in section
        assert "관리에 &amp; 관한" in section
        assert "- 전자 보관" in section

    def test_쪽_나눔이_들어간다(self, archive):
        section = archive.read("Contents/section0.xml").decode("utf-8")
        assert 'pageBreak="1"' in section

    def test_쪽_나눔을_끌_수_있다(self, document, tmp_path):
        options = ConvertOptions(page_break=False)
        path = get_writer("hwpx").write(document, tmp_path / "a.hwpx", options)
        with zipfile.ZipFile(path) as zf:
            assert 'pageBreak="1"' not in zf.read("Contents/section0.xml").decode()

    def test_글꼴_설정이_머리말에_반영된다(self, document, tmp_path):
        options = ConvertOptions(font_korean="함초롬바탕", font_size=12)
        path = get_writer("hwpx").write(document, tmp_path / "b.hwpx", options)
        with zipfile.ZipFile(path) as zf:
            header = zf.read("Contents/header.xml").decode()
        assert 'face="함초롬바탕"' in header
        assert 'height="1200"' in header    # 12pt = 1200 (1/100 pt)

    def test_선언한_개수와_실제_항목_수가_맞는다(self, document, tmp_path):
        # itemCnt가 실제와 다르면 한/글이 파일을 거부한다.
        path = get_writer("hwpx").write(document, tmp_path / "c.hwpx", ConvertOptions())
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("Contents/header.xml"))
        for element in root.iter():
            declared = element.get("itemCnt")
            if declared is not None:
                assert len(list(element)) == int(declared), element.tag


class TestHwpml:
    def test_올바른_XML이고_본문을_담는다(self, document, options, tmp_path):
        path = get_writer("hwpml").write(document, tmp_path / "결과.hwpml", options)
        root = ET.parse(path).getroot()
        assert root.tag == "HWPML"
        text = path.read_text(encoding="utf-8")
        assert "제1장 &lt;총칙&gt;" in text
        assert "<BODY>" in text

    def test_선언한_개수와_실제_항목_수가_맞는다(self, document, options, tmp_path):
        # COLDEF의 Count는 단 수여서 제외한다. 목록류만 자식 수와 맞아야 한다.
        path = get_writer("hwpml").write(document, tmp_path / "b.hwpml", options)
        for element in ET.parse(path).getroot().iter():
            declared = element.get("Count")
            if declared is None or not element.tag.endswith(("LIST", "FONTFACE")):
                continue
            assert len(list(element)) == int(declared), element.tag


class TestDocx:
    def test_문단과_제목이_들어간다(self, document, options, tmp_path):
        docx = pytest.importorskip("docx")
        path = get_writer("docx").write(document, tmp_path / "결과.docx", options)
        opened = docx.Document(str(path))
        texts = [p.text for p in opened.paragraphs]
        assert "문서 관리 규정" in texts
        assert "제1장 <총칙>" in texts
        assert any("전자 보관" in t for t in texts)

    def test_한글_글꼴이_eastAsia로_지정된다(self, document, tmp_path):
        docx = pytest.importorskip("docx")
        options = ConvertOptions(font_korean="맑은 고딕")
        path = get_writer("docx").write(document, tmp_path / "b.docx", options)
        xml = docx.Document(str(path)).paragraphs[1]._element.xml
        assert 'eastAsia="맑은 고딕"' in xml


class TestTextWriters:
    def test_txt는_목록_기호를_되살린다(self, document, options, tmp_path):
        path = get_writer("txt").write(document, tmp_path / "a.txt", options)
        assert "- 전자 보관" in path.read_text(encoding="utf-8")

    def test_md는_제목과_목록을_마크다운으로_쓴다(self, document, options, tmp_path):
        path = get_writer("md").write(document, tmp_path / "a.md", options)
        text = path.read_text(encoding="utf-8")
        assert "# 문서 관리 규정" in text
        assert "## 제1장 <총칙>" in text
        assert "- 전자 보관" in text
        assert "1. 보존 5년" in text

    def test_확장자를_형식에_맞게_바꾼다(self, tmp_path):
        assert get_writer("hwpx").target_path(tmp_path / "a").name == "a.hwpx"

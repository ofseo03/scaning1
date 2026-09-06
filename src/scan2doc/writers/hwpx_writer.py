"""한글 문서(.hwpx) 출력.

.hwpx는 한컴이 공개한 OWPML(KS X 6101) 표준으로, 여러 XML을 담은 ZIP이다.
바이너리 .hwp와 달리 문서화된 형식이라 외부 라이브러리 없이 만들 수 있고,
한/글 2014 이상에서 그대로 열리며 '다른 이름으로 저장'으로 .hwp가 된다.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ..config import ConvertOptions
from ..errors import WriterError
from ..model import BlockKind, Document
from .base import DocumentWriter, sanitize_xml_text

XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

NS_HEAD = "http://www.hancom.co.kr/hwpml/2011/head"
NS_SECTION = "http://www.hancom.co.kr/hwpml/2011/section"
NS_PARAGRAPH = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS_CORE = "http://www.hancom.co.kr/hwpml/2011/core"
NS_APP = "http://www.hancom.co.kr/hwpml/2011/app"
NS_VERSION = "http://www.hancom.co.kr/hwpml/2011/version"
NS_HPF = "http://www.hancom.co.kr/schema/2011/hpf"
NS_OPF = "http://www.idpf.org/2007/opf/"
NS_OCF = "urn:oasis:names:tc:opendocument:xmlns:container"
NS_ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
NS_DC = "http://purl.org/dc/elements/1.1/"

MIMETYPE = "application/hwp+zip"

#: HWPUNIT = 1/7200인치. 1pt = 100 HWPUNIT, 1mm ≈ 283.465 HWPUNIT
PT = 100
MM = 7200 / 25.4

# A4 세로
PAGE_WIDTH = 59528
PAGE_HEIGHT = 84188
MARGIN_LEFT = MARGIN_RIGHT = 8504     # 30mm
MARGIN_TOP = 5668                     # 20mm
MARGIN_BOTTOM = 4252                  # 15mm
MARGIN_HEADER = MARGIN_FOOTER = 4252
TEXT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

#: 글자모양 ID
CHAR_BODY, CHAR_H1, CHAR_H2, CHAR_H3 = 0, 1, 2, 3
#: 문단모양 ID
PARA_BODY, PARA_HEADING, PARA_LIST = 0, 1, 2
#: 스타일 ID
STYLE_BODY, STYLE_H1, STYLE_H2, STYLE_H3 = 0, 1, 2, 3

HEADING_SCALE = {1: 1.65, 2: 1.35, 3: 1.15}

#: 언어별 글꼴 묶음 (HWPX는 이 7가지를 모두 요구한다)
FONT_LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")

#: 목록 들여쓰기 한 단계 (10mm)
LIST_INDENT = int(10 * MM)


@dataclass
class _Paragraph:
    """section0.xml에 쓸 문단 하나."""

    text: str
    char_id: int = CHAR_BODY
    para_id: int = PARA_BODY
    style_id: int = STYLE_BODY
    page_break: bool = False
    height: int = 1100
    indent: int = 0


class HwpxWriter(DocumentWriter):
    name = "hwpx"
    extension = ".hwpx"
    description = "한글 문서 (OWPML 표준, 한/글 2014 이상)"

    def write(self, document: Document, path: Path, options: ConvertOptions) -> Path:
        paragraphs = _collect_paragraphs(document, options)
        title = document.title or path.stem

        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                # mimetype은 반드시 첫 항목이고 압축하지 않아야 한다.
                archive.writestr(
                    zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED
                )
                archive.writestr("version.xml", _version_xml())
                archive.writestr("META-INF/container.xml", _container_xml())
                archive.writestr("META-INF/manifest.xml", _manifest_xml())
                archive.writestr("META-INF/container.rdf", _container_rdf())
                archive.writestr("Contents/content.hpf", _content_hpf(title))
                archive.writestr("Contents/header.xml", _header_xml(options))
                archive.writestr("Contents/section0.xml", _section_xml(paragraphs))
                archive.writestr("settings.xml", _settings_xml())
                archive.writestr(
                    "Preview/PrvText.txt",
                    sanitize_xml_text(document.text)[:4000].encode("utf-8"),
                )
        except OSError as exc:
            raise WriterError(f"한글 문서를 저장하지 못했습니다: {path} ({exc})") from exc
        return path


# --- 문서 내용 -> 문단 목록 ----------------------------------------------

def _collect_paragraphs(document: Document, options: ConvertOptions) -> list[_Paragraph]:
    body_height = int(options.font_size * PT)
    paragraphs: list[_Paragraph] = []

    if document.title:
        paragraphs.append(
            _Paragraph(
                text=document.title,
                char_id=CHAR_H1,
                para_id=PARA_HEADING,
                style_id=STYLE_H1,
                height=int(body_height * HEADING_SCALE[1]),
            )
        )

    for page_index, page in enumerate(document.pages):
        first_of_page = True
        for block in page.blocks:
            if block.is_empty():
                continue
            page_break = (
                options.page_break and first_of_page and page_index > 0
            )
            first_of_page = False

            if block.kind is BlockKind.HEADING:
                level = min(3, max(1, block.level or 3))
                paragraphs.append(
                    _Paragraph(
                        text=block.text,
                        char_id={1: CHAR_H1, 2: CHAR_H2, 3: CHAR_H3}[level],
                        para_id=PARA_HEADING,
                        style_id={1: STYLE_H1, 2: STYLE_H2, 3: STYLE_H3}[level],
                        page_break=page_break,
                        height=int(body_height * HEADING_SCALE[level]),
                    )
                )
            elif block.kind is BlockKind.LIST_ITEM:
                marker = block.list_marker or "-"
                paragraphs.append(
                    _Paragraph(
                        text=f"{marker} {block.text}".strip(),
                        para_id=PARA_LIST,
                        page_break=page_break,
                        height=body_height,
                        indent=LIST_INDENT * (block.level + 1),
                    )
                )
            else:
                paragraphs.append(
                    _Paragraph(
                        text=block.text,
                        page_break=page_break,
                        height=body_height,
                    )
                )

    if not paragraphs:
        paragraphs.append(_Paragraph(text="", height=body_height))
    return paragraphs


# --- 개별 XML 조각 -------------------------------------------------------

def _version_xml() -> str:
    return (
        XML_DECL
        + f'<hv:HCFVersion xmlns:hv="{NS_VERSION}" tagetApplication="WORDPROCESSOR"'
        ' major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.4"'
        ' application="scan2doc" appVersion="0.1.0"/>'
    )


def _container_xml() -> str:
    return (
        XML_DECL
        + f'<ocf:container xmlns:ocf="{NS_OCF}" xmlns:hpf="{NS_HPF}">'
        "<ocf:rootfiles>"
        '<ocf:rootfile full-path="Contents/content.hpf"'
        ' media-type="application/hwpml-package+xml"/>'
        "</ocf:rootfiles></ocf:container>"
    )


def _manifest_xml() -> str:
    entries = [
        ("/", MIMETYPE),
        ("version.xml", "application/xml"),
        ("Contents/content.hpf", "application/xml"),
        ("Contents/header.xml", "application/xml"),
        ("Contents/section0.xml", "application/xml"),
        ("settings.xml", "application/xml"),
        ("Preview/PrvText.txt", "text/plain"),
    ]
    items = "".join(
        f'<odf:file-entry full-path="{path}" media-type="{media}"/>'
        for path, media in entries
    )
    return (
        XML_DECL
        + f'<odf:manifest xmlns:odf="{NS_ODF_MANIFEST}" version="1.2">'
        + items
        + "</odf:manifest>"
    )


def _container_rdf() -> str:
    return (
        XML_DECL
        + '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
        ' xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf#">'
        '<rdf:Description rdf:about="">'
        '<rdf:type rdf:resource="http://www.hancom.co.kr/schema/2011/hpf#Document"/>'
        "</rdf:Description></rdf:RDF>"
    )


def _content_hpf(title: str) -> str:
    safe_title = escape(sanitize_xml_text(title))
    return (
        XML_DECL
        + f'<hpf:package xmlns:hpf="{NS_HPF}" xmlns:opf="{NS_OPF}" xmlns:dc="{NS_DC}"'
        ' version="" unique-identifier="" id="">'
        "<hpf:metadata>"
        f"<opf:title>{safe_title}</opf:title>"
        "<opf:language>ko</opf:language>"
        '<opf:meta name="creator" content="scan2doc"/>'
        "</hpf:metadata>"
        "<hpf:manifest>"
        '<hpf:item id="header" href="Contents/header.xml" media-type="application/xml"'
        ' isEmbeded="0"/>'
        '<hpf:item id="section0" href="Contents/section0.xml" media-type="application/xml"'
        ' isEmbeded="0"/>'
        '<hpf:item id="settings" href="settings.xml" media-type="application/xml"'
        ' isEmbeded="0"/>'
        "</hpf:manifest>"
        "<hpf:spine>"
        '<hpf:itemref idref="header" linear="yes"/>'
        '<hpf:itemref idref="section0" linear="yes"/>'
        "</hpf:spine>"
        "</hpf:package>"
    )


def _settings_xml() -> str:
    return (
        XML_DECL
        + f'<ha:HWPApplicationSetting xmlns:ha="{NS_APP}">'
        '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
        "</ha:HWPApplicationSetting>"
    )


def _header_xml(options: ConvertOptions) -> str:
    body = int(options.font_size * PT)
    spacing = int(options.line_spacing * 100)
    parts = [
        XML_DECL,
        f'<hh:head xmlns:hh="{NS_HEAD}" xmlns:hp="{NS_PARAGRAPH}" xmlns:hc="{NS_CORE}"'
        ' version="1.4" secCnt="1">',
        '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>',
        "<hh:refList>",
        _fontfaces(options),
        _border_fills(),
        _char_properties(body, options),
        '<hh:tabProperties itemCnt="1">'
        '<hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>'
        "</hh:tabProperties>",
        _numberings(),
        _bullets(),
        _para_properties(spacing),
        _styles(),
        "</hh:refList>",
        '<hh:compatibleDocument targetProgram="HWP201X">'
        "<hh:layoutCompatibility/></hh:compatibleDocument>",
        "<hh:docOption>"
        '<hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/>'
        "</hh:docOption>",
        '<hh:trackchageConfig flags="0"/>',
        "</hh:head>",
    ]
    return "".join(parts)


def _fontfaces(options: ConvertOptions) -> str:
    """언어 묶음마다 글꼴 하나씩(id=0)만 등록한다."""
    chunks = [f'<hh:fontfaces itemCnt="{len(FONT_LANGS)}">']
    for lang in FONT_LANGS:
        face = options.font_korean if lang in ("HANGUL", "HANJA", "JAPANESE") else options.font_latin
        chunks.append(
            f'<hh:fontface lang="{lang}" fontCnt="1">'
            f"<hh:font id=\"0\" face={quoteattr(face)} type=\"TTF\" isEmbedded=\"0\">"
            '<hh:typeInfo familyType="FCAT_GOTHIC" serifStyle="0" weight="6" proportion="4"'
            ' contrast="0" strokeVariation="1" armStyle="0" letterform="1" midline="1"'
            ' xHeight="1"/>'
            "</hh:font></hh:fontface>"
        )
    chunks.append("</hh:fontfaces>")
    return "".join(chunks)


def _border_fills() -> str:
    def fill(idx: int) -> str:
        sides = "".join(
            f'<hh:{side} type="NONE" width="0.1 mm" color="#000000"/>'
            for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder")
        )
        return (
            f'<hh:borderFill id="{idx}" threeD="0" shadow="0" centerLine="NONE"'
            ' breakCellSeparateLine="0">'
            '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
            '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            + sides
            + '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
            "</hh:borderFill>"
        )

    return '<hh:borderFills itemCnt="2">' + fill(1) + fill(2) + "</hh:borderFills>"


def _char_properties(body: int, options: ConvertOptions) -> str:
    def char_pr(idx: int, height: int, bold: bool) -> str:
        return (
            f'<hh:charPr id="{idx}" height="{height}" textColor="#000000" shadeColor="none"'
            ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">'
            '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0"'
            ' symbol="0" user="0"/>'
            '<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100"'
            ' symbol="100" user="100"/>'
            '<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0"'
            ' symbol="0" user="0"/>'
            '<hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100"'
            ' symbol="100" user="100"/>'
            '<hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0"'
            ' symbol="0" user="0"/>'
            + ("<hh:bold/>" if bold else "")
            + "</hh:charPr>"
        )

    items = [
        char_pr(CHAR_BODY, body, False),
        char_pr(CHAR_H1, int(body * HEADING_SCALE[1]), True),
        char_pr(CHAR_H2, int(body * HEADING_SCALE[2]), True),
        char_pr(CHAR_H3, int(body * HEADING_SCALE[3]), True),
    ]
    return f'<hh:charProperties itemCnt="{len(items)}">' + "".join(items) + "</hh:charProperties>"


def _numberings() -> str:
    heads = "".join(
        f'<hh:paraHead start="1" level="{level}" align="LEFT" useInstWidth="1"'
        ' autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50"'
        ' numFormat="DIGIT" charPrIDRef="4294967295" checkable="0">^'
        f"{level}.</hh:paraHead>"
        for level in range(1, 8)
    )
    return (
        '<hh:numberings itemCnt="1">'
        '<hh:numbering id="1" start="1">' + heads + "</hh:numbering>"
        "</hh:numberings>"
    )


def _bullets() -> str:
    return (
        '<hh:bullets itemCnt="1">'
        '<hh:bullet id="1" char="●" checkable="0" useImage="0">'
        '<hh:paraHead start="1" level="1" align="LEFT" useInstWidth="1" autoIndent="1"'
        ' widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="DIGIT"'
        ' charPrIDRef="4294967295" checkable="0"/>'
        "</hh:bullet></hh:bullets>"
    )


def _para_properties(spacing: int) -> str:
    def para_pr(idx: int, align: str, left: int, indent: int,
                prev: int, nxt: int, line_spacing: int) -> str:
        return (
            f'<hh:paraPr id="{idx}" tabPrIDRef="0" condense="0" fontLineHeight="0"'
            ' snapToGrid="1" suppressLineNumbers="0" checked="0">'
            f'<hh:align horizontal="{align}" vertical="BASELINE"/>'
            '<hh:heading type="NONE" idRef="0" level="0"/>'
            '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"'
            ' widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0"'
            ' lineWrap="BREAK"/>'
            '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            "<hh:margin>"
            f'<hc:intent value="{indent}" unit="HWPUNIT"/>'
            f'<hc:left value="{left}" unit="HWPUNIT"/>'
            '<hc:right value="0" unit="HWPUNIT"/>'
            f'<hc:prev value="{prev}" unit="HWPUNIT"/>'
            f'<hc:next value="{nxt}" unit="HWPUNIT"/>'
            "</hh:margin>"
            f'<hh:lineSpacing type="PERCENT" value="{line_spacing}" unit="HWPUNIT"/>'
            '<hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0"'
            ' offsetBottom="0" connect="0" ignoreMargin="0"/>'
            "</hh:paraPr>"
        )

    items = [
        para_pr(PARA_BODY, "JUSTIFY", 0, 0, 0, 300, spacing),
        para_pr(PARA_HEADING, "LEFT", 0, 0, 800, 400, 130),
        # 목록: 왼쪽 여백 + 음수 들여쓰기로 기호를 바깥에 걸어 둔다.
        para_pr(PARA_LIST, "LEFT", LIST_INDENT, -LIST_INDENT, 0, 200, spacing),
    ]
    return f'<hh:paraProperties itemCnt="{len(items)}">' + "".join(items) + "</hh:paraProperties>"


def _styles() -> str:
    definitions = [
        (STYLE_BODY, "바탕글", "Normal", PARA_BODY, CHAR_BODY),
        (STYLE_H1, "제목 1", "Heading 1", PARA_HEADING, CHAR_H1),
        (STYLE_H2, "제목 2", "Heading 2", PARA_HEADING, CHAR_H2),
        (STYLE_H3, "제목 3", "Heading 3", PARA_HEADING, CHAR_H3),
    ]
    items = "".join(
        f'<hh:style id="{idx}" type="PARA" name={quoteattr(name)}'
        f" engName={quoteattr(eng)} paraPrIDRef=\"{para}\" charPrIDRef=\"{char}\""
        f' nextStyleIDRef="{STYLE_BODY}" langID="1042" lockForm="0"/>'
        for idx, name, eng, para, char in definitions
    )
    return f'<hh:styles itemCnt="{len(definitions)}">' + items + "</hh:styles>"


def _section_xml(paragraphs: list[_Paragraph]) -> str:
    chunks = [
        XML_DECL,
        f'<hs:sec xmlns:hs="{NS_SECTION}" xmlns:hp="{NS_PARAGRAPH}" xmlns:hc="{NS_CORE}">',
    ]
    for index, para in enumerate(paragraphs):
        chunks.append(_paragraph_xml(index, para, include_secpr=(index == 0)))
    chunks.append("</hs:sec>")
    return "".join(chunks)


def _paragraph_xml(index: int, para: _Paragraph, *, include_secpr: bool) -> str:
    text = _run_text(para.text)
    inner = _sec_pr() if include_secpr else ""
    baseline = int(para.height * 0.85)
    line_spacing = int(para.height * 0.6)
    horz_size = max(1000, TEXT_WIDTH - para.indent)

    return (
        f'<hp:p id="{index}" paraPrIDRef="{para.para_id}" styleIDRef="{para.style_id}"'
        f' pageBreak="{1 if para.page_break else 0}" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{para.char_id}">{inner}{text}</hp:run>'
        "<hp:linesegarray>"
        f'<hp:lineseg textpos="0" vertpos="0" vertsize="{para.height}"'
        f' textheight="{para.height}" baseline="{baseline}" spacing="{line_spacing}"'
        f' horzpos="0" horzsize="{horz_size}" flags="393216"/>'
        "</hp:linesegarray>"
        "</hp:p>"
    )


def _run_text(text: str) -> str:
    """문단 본문을 <hp:t>로 만든다. 줄바꿈은 <hp:lineBreak/>로 옮긴다."""
    clean = sanitize_xml_text(text)
    if not clean:
        return "<hp:t></hp:t>"
    pieces = [escape(line) for line in clean.split("\n")]
    return "<hp:t>" + "<hp:lineBreak/>".join(pieces) + "</hp:t>"


def _sec_pr() -> str:
    """첫 문단에 들어가는 구역 설정(용지 크기, 여백 등)."""
    page_border = "".join(
        f'<hp:pageBorderFill type="{kind}" borderFillIDRef="1" textBorder="PAPER"'
        ' headerInside="0" footerInside="0" fillArea="PAPER">'
        '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
        "</hp:pageBorderFill>"
        for kind in ("BOTH", "EVEN", "ODD")
    )
    return (
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000"'
        ' tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0"'
        ' textVerticalWidthHead="0" masterPageCnt="0">'
        '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" strtnum="0"/>'
        '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0"'
        ' border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0"'
        ' showLineNumber="0"/>'
        '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
        f'<hp:pagePr landscape="NARROWLY" width="{PAGE_WIDTH}" height="{PAGE_HEIGHT}"'
        ' gutterType="LEFT_ONLY">'
        f'<hp:margin header="{MARGIN_HEADER}" footer="{MARGIN_FOOTER}" gutter="0"'
        f' left="{MARGIN_LEFT}" right="{MARGIN_RIGHT}" top="{MARGIN_TOP}"'
        f' bottom="{MARGIN_BOTTOM}"/>'
        "</hp:pagePr>"
        "<hp:footNotePr>"
        '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
        ' supscript="0"/>'
        '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hp:noteSpacing betweenNotes="850" belowLine="567" aboveLine="850"/>'
        '<hp:numbering type="CONTINUOUS" newNum="1"/>'
        '<hp:placement place="EACH_COLUMN" beneathText="0"/>'
        "</hp:footNotePr>"
        "<hp:endNotePr>"
        '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")"'
        ' supscript="0"/>'
        '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
        '<hp:numbering type="CONTINUOUS" newNum="1"/>'
        '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/>'
        "</hp:endNotePr>"
        + page_border
        + "</hp:secPr>"
        '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1"'
        ' sameGap="0"/></hp:ctrl>'
    )

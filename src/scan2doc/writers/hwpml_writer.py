"""한글 문서(.hwpml) 출력 — 구버전 한/글용 대체 형식.

.hwpx를 열지 못하는 예전 한/글(2007~2010)을 위한 단일 XML 형식이다.
기본값은 .hwpx이고, `--hwp-format hwpml`로 이 형식을 고를 수 있다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ..config import ConvertOptions
from ..errors import WriterError
from ..model import BlockKind, Document
from .base import DocumentWriter, sanitize_xml_text
from .hwpx_writer import (
    HEADING_SCALE,
    LIST_INDENT,
    MARGIN_BOTTOM,
    MARGIN_FOOTER,
    MARGIN_HEADER,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PT,
    _collect_paragraphs,
)

FONT_LANGS = ("Hangul", "Latin", "Hanja", "Japanese", "Other", "Symbol", "User")
LANG_ATTRS = ("Hangul", "Latin", "Hanja", "Japanese", "Other", "Symbol", "User")


class HwpmlWriter(DocumentWriter):
    name = "hwpml"
    extension = ".hwpml"
    description = "한글 문서 (구버전 HWPML, 한/글 2007 이상)"

    def write(self, document: Document, path: Path, options: ConvertOptions) -> Path:
        paragraphs = _collect_paragraphs(document, options)
        xml = "".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>\n',
                '<HWPML Version="2.8" SubVersion="8.0.0.0" Style="embed">',
                _head(document, options),
                _body(paragraphs),
                "</HWPML>",
            ]
        )
        try:
            path.write_text(xml, encoding="utf-8")
        except OSError as exc:
            raise WriterError(f"한글 문서를 저장하지 못했습니다: {path} ({exc})") from exc
        return path


def _head(document: Document, options: ConvertOptions) -> str:
    title = escape(sanitize_xml_text(document.title or ""))
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    body = int(options.font_size * PT)
    spacing = int(options.line_spacing * 100)
    return (
        '<HEAD SecCnt="1">'
        f"<DOCSUMMARY><TITLE>{title}</TITLE><AUTHOR>scan2doc</AUTHOR>"
        f"<DATE>{now}</DATE></DOCSUMMARY>"
        "<DOCSETTING>"
        '<BEGINNUMBER Page="1" Footnote="1" Endnote="1" Picture="1" Table="1" Equation="1"/>'
        '<CARETPOS List="0" Para="0" Pos="0"/>'
        "</DOCSETTING>"
        "<MAPPINGTABLE>"
        + _facenames(options)
        + _borderfills()
        + _charshapes(body)
        + '<TABDEFLIST Count="1"><TABDEF Id="0" AutoTabLeft="false" AutoTabRight="false"/>'
          "</TABDEFLIST>"
        + _numberings()
        + '<BULLETLIST Count="0"/>'
        + _parashapes(spacing)
        + _styles()
        + "</MAPPINGTABLE>"
        '<COMPATIBLEDOCUMENT TargetProgram="HWP201X"><LAYOUTCOMPATIBILITY/>'
        "</COMPATIBLEDOCUMENT>"
        "</HEAD>"
    )


def _facenames(options: ConvertOptions) -> str:
    chunks = [f'<FACENAMELIST Count="{len(FONT_LANGS)}">']
    for lang in FONT_LANGS:
        face = options.font_korean if lang in ("Hangul", "Hanja", "Japanese") else options.font_latin
        chunks.append(
            f'<FONTFACE Lang="{lang}" Count="1">'
            f"<FONT Id=\"0\" Type=\"TTF\" Name={quoteattr(face)}>"
            '<TYPEINFO FamilyType="FCAT_GOTHIC" SerifStyle="0" Weight="0" Proportion="0"'
            ' Contrast="0" StrokeVariation="0" ArmStyle="0" Letterform="0" Midline="0"'
            ' XHeight="0"/>'
            "</FONT></FONTFACE>"
        )
    chunks.append("</FACENAMELIST>")
    return "".join(chunks)


def _borderfills() -> str:
    sides = "".join(
        f'<{side} Type="None" Width="0.1mm" Color="0"/>'
        for side in ("LEFTBORDER", "RIGHTBORDER", "TOPBORDER", "BOTTOMBORDER", "DIAGONAL")
    )
    return (
        '<BORDERFILLLIST Count="1">'
        '<BORDERFILL Id="1" ThreeD="false" Shadow="false" Slash="0" BackSlash="0"'
        ' CrookedSlash="0" CounterSlash="false" CounterBackSlash="false"'
        ' BreakCellSeparateLine="false">'
        + sides
        + "</BORDERFILL></BORDERFILLLIST>"
    )


def _lang_attrs(name: str, value: int | str) -> str:
    return " ".join(f'{lang}="{value}"' for lang in LANG_ATTRS)


def _charshapes(body: int) -> str:
    def charshape(idx: int, height: int, bold: bool) -> str:
        return (
            f'<CHARSHAPE Id="{idx}" Height="{height}" TextColor="0" ShadeColor="4294967295"'
            ' UseFontSpace="false" UseKerning="false" SymMark="None" BorderFill="1">'
            f"<FONTID {_lang_attrs('FONTID', 0)}/>"
            f"<RATIO {_lang_attrs('RATIO', 100)}/>"
            f"<CHARSPACING {_lang_attrs('CHARSPACING', 0)}/>"
            f"<RELSIZE {_lang_attrs('RELSIZE', 100)}/>"
            f"<CHARPOSITION {_lang_attrs('CHARPOSITION', 0)}/>"
            + ("<BOLD/>" if bold else "")
            + "</CHARSHAPE>"
        )

    items = [
        charshape(0, body, False),
        charshape(1, int(body * HEADING_SCALE[1]), True),
        charshape(2, int(body * HEADING_SCALE[2]), True),
        charshape(3, int(body * HEADING_SCALE[3]), True),
    ]
    return f'<CHARSHAPELIST Count="{len(items)}">' + "".join(items) + "</CHARSHAPELIST>"


def _numberings() -> str:
    heads = "".join(
        f'<PARAHEAD Start="1" Level="{level}" Align="Left" UseInstWidth="true"'
        ' AutoIndent="true" WidthAdjust="0" TextOffsetType="Percent" TextOffset="50"'
        f' NumFormat="Digit" CharShape="0">^{level}.</PARAHEAD>'
        for level in range(1, 8)
    )
    return (
        '<NUMBERINGLIST Count="1"><NUMBERING Id="1" Start="1">'
        + heads
        + "</NUMBERING></NUMBERINGLIST>"
    )


def _parashapes(spacing: int) -> str:
    def parashape(idx: int, align: str, left: int, indent: int,
                  prev: int, nxt: int, line_spacing: int) -> str:
        return (
            f'<PARASHAPE Id="{idx}" Align="{align}" VerAlign="Baseline" HeadingType="None"'
            ' Heading="0" Level="0" TabDef="0" BreakLatinWord="KeepWord"'
            ' BreakNonLatinWord="KeepWord" Condense="0" WidowOrphan="false"'
            ' KeepWithNext="false" KeepLines="false" PageBreakBefore="false"'
            ' FontLineHeight="false" SnapToGrid="true" LineWrap="Break"'
            ' AutoSpaceEAsianEng="true" AutoSpaceEAsianNum="true"'
            ' SuppressLineNumbers="false" Checked="false">'
            f'<PARAMARGIN Indent="{indent}" Left="{left}" Right="0" Prev="{prev}"'
            f' Next="{nxt}"/>'
            f'<LINESPACING Type="Percent" Value="{line_spacing}"/>'
            '<PARABORDER BorderFill="1" OffsetLeft="0" OffsetRight="0" OffsetTop="0"'
            ' OffsetBottom="0" Connect="false" IgnoreMargin="false"/>'
            "</PARASHAPE>"
        )

    items = [
        parashape(0, "Justify", 0, 0, 0, 300, spacing),
        parashape(1, "Left", 0, 0, 800, 400, 130),
        parashape(2, "Left", LIST_INDENT, -LIST_INDENT, 0, 200, spacing),
    ]
    return f'<PARASHAPELIST Count="{len(items)}">' + "".join(items) + "</PARASHAPELIST>"


def _styles() -> str:
    definitions = [
        (0, "바탕글", "Normal", 0, 0),
        (1, "제목 1", "Heading 1", 1, 1),
        (2, "제목 2", "Heading 2", 1, 2),
        (3, "제목 3", "Heading 3", 1, 3),
    ]
    items = "".join(
        f'<STYLE Id="{idx}" Type="Para" Name={quoteattr(name)} EngName={quoteattr(eng)}'
        f' ParaShape="{para}" CharShape="{char}" NextStyle="0" LangId="1042"'
        ' LockForm="false"/>'
        for idx, name, eng, para, char in definitions
    )
    return f'<STYLELIST Count="{len(definitions)}">' + items + "</STYLELIST>"


def _body(paragraphs) -> str:
    chunks = ['<BODY><SECTION Id="0">']
    for index, para in enumerate(paragraphs):
        secdef = _secdef() if index == 0 else ""
        text = _char_xml(para.text)
        chunks.append(
            f'<P ParaShape="{para.para_id}" Style="{para.style_id}"'
            f' PageBreak="{"true" if para.page_break else "false"}" ColumnBreak="false">'
            f'<TEXT CharShape="{para.char_id}">{secdef}{text}</TEXT>'
            "</P>"
        )
    chunks.append("</SECTION></BODY>")
    return "".join(chunks)


def _char_xml(text: str) -> str:
    clean = sanitize_xml_text(text)
    if not clean:
        return "<CHAR></CHAR>"
    pieces = [escape(line) for line in clean.split("\n")]
    return "<CHAR>" + "<LINEBREAK/>".join(pieces) + "</CHAR>"


def _secdef() -> str:
    return (
        '<SECDEF TextDirection="0" SpaceColumns="1134" TabStop="8000" OutlineShape="1"'
        ' MemoShape="0" TextVerticalWidthHead="0">'
        '<STARTNUMBER PageStartsOn="Both" Page="0" Picture="0" Table="0" Equation="0"/>'
        '<HIDE Header="false" Footer="false" MasterPage="false" Border="false"'
        ' Fill="false" PageNumPos="false" EmptyLine="false"/>'
        f'<PAGEDEF Landscape="0" Width="{PAGE_WIDTH}" Height="{PAGE_HEIGHT}"'
        ' GutterType="LeftOnly">'
        f'<PAGEMARGIN Left="{MARGIN_LEFT}" Right="{MARGIN_RIGHT}" Top="{MARGIN_TOP}"'
        f' Bottom="{MARGIN_BOTTOM}" Header="{MARGIN_HEADER}" Footer="{MARGIN_FOOTER}"'
        ' Gutter="0"/>'
        "</PAGEDEF>"
        "<FOOTNOTESHAPE>"
        '<AUTONUMFORMAT Type="Digit" UserChar="" PrefixChar="" SuffixChar=")"'
        ' Superscript="false"/>'
        '<NOTELINE Length="-1" Type="Solid" Width="0.12mm" Color="0"/>'
        '<NOTESPACING BetweenNotes="850" BelowLine="567" AboveLine="850"/>'
        '<NUMBERING Type="Continuous" NewNumber="1"/>'
        '<PLACEMENT Place="EachColumn" BeneathText="false"/>'
        "</FOOTNOTESHAPE>"
        "</SECDEF>"
        '<COLDEF Type="Newspaper" Count="1" Layout="Left" SameSize="true" SameGap="0"/>'
    )

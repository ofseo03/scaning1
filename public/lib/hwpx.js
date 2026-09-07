// 한글 문서(.hwpx) 만들기 — 파이썬 scan2doc/writers/hwpx_writer.py 를 옮긴 것이다.
// OWPML(KS X 6101) 규격대로 ZIP 안에 XML 을 넣는다. 한/글 2014 이상에서 열린다.

import { makeZip, xmlEscape } from './zip.js';

const XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';

const NS_HEAD = 'http://www.hancom.co.kr/hwpml/2011/head';
const NS_SECTION = 'http://www.hancom.co.kr/hwpml/2011/section';
const NS_PARA = 'http://www.hancom.co.kr/hwpml/2011/paragraph';
const NS_CORE = 'http://www.hancom.co.kr/hwpml/2011/core';
const NS_APP = 'http://www.hancom.co.kr/hwpml/2011/app';
const NS_VERSION = 'http://www.hancom.co.kr/hwpml/2011/version';
const NS_HPF = 'http://www.hancom.co.kr/schema/2011/hpf';
const NS_OPF = 'http://www.idpf.org/2007/opf/';
const NS_OCF = 'urn:oasis:names:tc:opendocument:xmlns:container';
const NS_ODF_MANIFEST = 'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0';
const NS_DC = 'http://purl.org/dc/elements/1.1/';

export const MIMETYPE = 'application/hwp+zip';

// HWPUNIT = 1/7200인치. 1pt = 100 HWPUNIT, 1mm ≈ 283.465 HWPUNIT
const PT = 100;
const MM = 7200 / 25.4;

// A4 세로
const PAGE_WIDTH = 59528;
const PAGE_HEIGHT = 84188;
const MARGIN_LEFT = 8504, MARGIN_RIGHT = 8504;   // 30mm
const MARGIN_TOP = 5668, MARGIN_BOTTOM = 4252;
const MARGIN_HEADER = 4252, MARGIN_FOOTER = 4252;
const TEXT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT;

const CHAR_BODY = 0, CHAR_H1 = 1, CHAR_H2 = 2, CHAR_H3 = 3;
const PARA_BODY = 0, PARA_HEADING = 1, PARA_LIST = 2;
const STYLE_BODY = 0, STYLE_H1 = 1, STYLE_H2 = 2, STYLE_H3 = 3;

const HEADING_SCALE = { 1: 1.65, 2: 1.35, 3: 1.15 };
const FONT_LANGS = ['HANGUL', 'LATIN', 'HANJA', 'JAPANESE', 'OTHER', 'SYMBOL', 'USER'];
const LIST_INDENT = Math.round(10 * MM);

const attr = (value) => `"${xmlEscape(value)}"`;

/** 문서 모델 → hwpx 문단 목록 */
function collectParagraphs(doc, options) {
  const body = Math.round(options.fontSize * PT);
  const paragraphs = [];

  if (doc.title) {
    paragraphs.push({
      text: doc.title, charId: CHAR_H1, paraId: PARA_HEADING, styleId: STYLE_H1,
      height: Math.round(body * HEADING_SCALE[1]), pageBreak: false, indent: 0,
    });
  }

  doc.pages.forEach((page, pageIndex) => {
    let first = true;
    for (const block of page.blocks) {
      if (!block.text || !block.text.trim()) continue;
      const pageBreak = options.pageBreak && first && pageIndex > 0;
      first = false;

      if (block.kind === 'heading') {
        const level = Math.min(3, Math.max(1, block.level || 3));
        paragraphs.push({
          text: block.text,
          charId: { 1: CHAR_H1, 2: CHAR_H2, 3: CHAR_H3 }[level],
          paraId: PARA_HEADING,
          styleId: { 1: STYLE_H1, 2: STYLE_H2, 3: STYLE_H3 }[level],
          height: Math.round(body * HEADING_SCALE[level]),
          pageBreak, indent: 0,
        });
      } else if (block.kind === 'list_item') {
        const marker = block.listMarker || '-';
        paragraphs.push({
          text: `${marker} ${block.text}`.trim(),
          charId: CHAR_BODY, paraId: PARA_LIST, styleId: STYLE_BODY,
          height: body, pageBreak, indent: LIST_INDENT * ((block.level || 0) + 1),
        });
      } else {
        paragraphs.push({
          text: block.text, charId: CHAR_BODY, paraId: PARA_BODY, styleId: STYLE_BODY,
          height: body, pageBreak, indent: 0,
        });
      }
    }
  });

  if (!paragraphs.length) {
    paragraphs.push({ text: '', charId: CHAR_BODY, paraId: PARA_BODY, styleId: STYLE_BODY,
                      height: body, pageBreak: false, indent: 0 });
  }
  return paragraphs;
}

const versionXml = () => XML_DECL
  + `<hv:HCFVersion xmlns:hv="${NS_VERSION}" tagetApplication="WORDPROCESSOR"`
  + ' major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.4"'
  + ' application="scan2doc" appVersion="0.1.0"/>';

const containerXml = () => XML_DECL
  + `<ocf:container xmlns:ocf="${NS_OCF}" xmlns:hpf="${NS_HPF}">`
  + '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf"'
  + ' media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>';

const manifestXml = () => {
  const entries = [
    ['/', MIMETYPE],
    ['version.xml', 'application/xml'],
    ['Contents/content.hpf', 'application/xml'],
    ['Contents/header.xml', 'application/xml'],
    ['Contents/section0.xml', 'application/xml'],
    ['settings.xml', 'application/xml'],
    ['Preview/PrvText.txt', 'text/plain'],
  ];
  return XML_DECL + `<odf:manifest xmlns:odf="${NS_ODF_MANIFEST}" version="1.2">`
    + entries.map(([p, m]) => `<odf:file-entry full-path="${p}" media-type="${m}"/>`).join('')
    + '</odf:manifest>';
};

const containerRdf = () => XML_DECL
  + '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
  + ' xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf#">'
  + '<rdf:Description rdf:about="">'
  + '<rdf:type rdf:resource="http://www.hancom.co.kr/schema/2011/hpf#Document"/>'
  + '</rdf:Description></rdf:RDF>';

const contentHpf = (title) => XML_DECL
  + `<hpf:package xmlns:hpf="${NS_HPF}" xmlns:opf="${NS_OPF}" xmlns:dc="${NS_DC}"`
  + ' version="" unique-identifier="" id="">'
  + `<hpf:metadata><opf:title>${xmlEscape(title)}</opf:title>`
  + '<opf:language>ko</opf:language>'
  + '<opf:meta name="creator" content="scan2doc"/></hpf:metadata>'
  + '<hpf:manifest>'
  + '<hpf:item id="header" href="Contents/header.xml" media-type="application/xml" isEmbeded="0"/>'
  + '<hpf:item id="section0" href="Contents/section0.xml" media-type="application/xml" isEmbeded="0"/>'
  + '<hpf:item id="settings" href="settings.xml" media-type="application/xml" isEmbeded="0"/>'
  + '</hpf:manifest>'
  + '<hpf:spine><hpf:itemref idref="header" linear="yes"/>'
  + '<hpf:itemref idref="section0" linear="yes"/></hpf:spine></hpf:package>';

const settingsXml = () => XML_DECL
  + `<ha:HWPApplicationSetting xmlns:ha="${NS_APP}">`
  + '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/></ha:HWPApplicationSetting>';

function fontfaces(options) {
  const parts = [`<hh:fontfaces itemCnt="${FONT_LANGS.length}">`];
  for (const lang of FONT_LANGS) {
    const face = ['HANGUL', 'HANJA', 'JAPANESE'].includes(lang)
      ? options.fontKorean : options.fontLatin;
    parts.push(`<hh:fontface lang="${lang}" fontCnt="1">`
      + `<hh:font id="0" face=${attr(face)} type="TTF" isEmbedded="0">`
      + '<hh:typeInfo familyType="FCAT_GOTHIC" serifStyle="0" weight="6" proportion="4"'
      + ' contrast="0" strokeVariation="1" armStyle="0" letterform="1" midline="1"'
      + ' xHeight="1"/></hh:font></hh:fontface>');
  }
  parts.push('</hh:fontfaces>');
  return parts.join('');
}

function borderFills() {
  const fill = (id) => {
    const sides = ['leftBorder', 'rightBorder', 'topBorder', 'bottomBorder']
      .map((s) => `<hh:${s} type="NONE" width="0.1 mm" color="#000000"/>`).join('');
    return `<hh:borderFill id="${id}" threeD="0" shadow="0" centerLine="NONE"`
      + ' breakCellSeparateLine="0">'
      + '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
      + '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
      + sides
      + '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/></hh:borderFill>';
  };
  return `<hh:borderFills itemCnt="2">${fill(1)}${fill(2)}</hh:borderFills>`;
}

function charProperties(body) {
  const charPr = (id, height, bold) =>
    `<hh:charPr id="${id}" height="${height}" textColor="#000000" shadeColor="none"`
    + ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">'
    + '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
    + '<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>'
    + '<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
    + '<hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>'
    + '<hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
    + (bold ? '<hh:bold/>' : '') + '</hh:charPr>';
  const items = [
    charPr(CHAR_BODY, body, false),
    charPr(CHAR_H1, Math.round(body * HEADING_SCALE[1]), true),
    charPr(CHAR_H2, Math.round(body * HEADING_SCALE[2]), true),
    charPr(CHAR_H3, Math.round(body * HEADING_SCALE[3]), true),
  ];
  return `<hh:charProperties itemCnt="${items.length}">${items.join('')}</hh:charProperties>`;
}

function numberings() {
  let heads = '';
  for (let level = 1; level <= 7; level++) {
    heads += `<hh:paraHead start="1" level="${level}" align="LEFT" useInstWidth="1"`
      + ' autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50"'
      + ` numFormat="DIGIT" charPrIDRef="4294967295" checkable="0">^${level}.</hh:paraHead>`;
  }
  return `<hh:numberings itemCnt="1"><hh:numbering id="1" start="1">${heads}</hh:numbering></hh:numberings>`;
}

const bullets = () => '<hh:bullets itemCnt="1">'
  + '<hh:bullet id="1" char="●" checkable="0" useImage="0">'
  + '<hh:paraHead start="1" level="1" align="LEFT" useInstWidth="1" autoIndent="1"'
  + ' widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="DIGIT"'
  + ' charPrIDRef="4294967295" checkable="0"/></hh:bullet></hh:bullets>';

function paraProperties(spacing) {
  const paraPr = (id, align, left, indent, prev, next, lineSpacing) =>
    `<hh:paraPr id="${id}" tabPrIDRef="0" condense="0" fontLineHeight="0"`
    + ' snapToGrid="1" suppressLineNumbers="0" checked="0">'
    + `<hh:align horizontal="${align}" vertical="BASELINE"/>`
    + '<hh:heading type="NONE" idRef="0" level="0"/>'
    + '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"'
    + ' widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>'
    + '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
    + '<hh:margin>'
    + `<hc:intent value="${indent}" unit="HWPUNIT"/>`
    + `<hc:left value="${left}" unit="HWPUNIT"/>`
    + '<hc:right value="0" unit="HWPUNIT"/>'
    + `<hc:prev value="${prev}" unit="HWPUNIT"/>`
    + `<hc:next value="${next}" unit="HWPUNIT"/>`
    + '</hh:margin>'
    + `<hh:lineSpacing type="PERCENT" value="${lineSpacing}" unit="HWPUNIT"/>`
    + '<hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0"'
    + ' offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr>';
  const items = [
    paraPr(PARA_BODY, 'JUSTIFY', 0, 0, 0, 300, spacing),
    paraPr(PARA_HEADING, 'LEFT', 0, 0, 800, 400, 130),
    paraPr(PARA_LIST, 'LEFT', LIST_INDENT, -LIST_INDENT, 0, 200, spacing),
  ];
  return `<hh:paraProperties itemCnt="${items.length}">${items.join('')}</hh:paraProperties>`;
}

function styles() {
  const defs = [
    [STYLE_BODY, '바탕글', 'Normal', PARA_BODY, CHAR_BODY],
    [STYLE_H1, '제목 1', 'Heading 1', PARA_HEADING, CHAR_H1],
    [STYLE_H2, '제목 2', 'Heading 2', PARA_HEADING, CHAR_H2],
    [STYLE_H3, '제목 3', 'Heading 3', PARA_HEADING, CHAR_H3],
  ];
  const items = defs.map(([id, name, eng, para, char]) =>
    `<hh:style id="${id}" type="PARA" name=${attr(name)} engName=${attr(eng)}`
    + ` paraPrIDRef="${para}" charPrIDRef="${char}" nextStyleIDRef="${STYLE_BODY}"`
    + ' langID="1042" lockForm="0"/>').join('');
  return `<hh:styles itemCnt="${defs.length}">${items}</hh:styles>`;
}

function headerXml(options) {
  const body = Math.round(options.fontSize * PT);
  const spacing = Math.round(options.lineSpacing * 100);
  return XML_DECL
    + `<hh:head xmlns:hh="${NS_HEAD}" xmlns:hp="${NS_PARA}" xmlns:hc="${NS_CORE}"`
    + ' version="1.4" secCnt="1">'
    + '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
    + '<hh:refList>'
    + fontfaces(options) + borderFills() + charProperties(body)
    + '<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>'
    + numberings() + bullets() + paraProperties(spacing) + styles()
    + '</hh:refList>'
    + '<hh:compatibleDocument targetProgram="HWP201X"><hh:layoutCompatibility/></hh:compatibleDocument>'
    + '<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>'
    + '<hh:trackchageConfig flags="0"/></hh:head>';
}

function secPr() {
  const pageBorder = ['BOTH', 'EVEN', 'ODD'].map((kind) =>
    `<hp:pageBorderFill type="${kind}" borderFillIDRef="1" textBorder="PAPER"`
    + ' headerInside="0" footerInside="0" fillArea="PAPER">'
    + '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>').join('');
  return '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000"'
    + ' tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0"'
    + ' textVerticalWidthHead="0" masterPageCnt="0">'
    + '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" strtnum="0"/>'
    + '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
    + '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0"'
    + ' border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0"'
    + ' showLineNumber="0"/>'
    + '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
    + `<hp:pagePr landscape="NARROWLY" width="${PAGE_WIDTH}" height="${PAGE_HEIGHT}"`
    + ' gutterType="LEFT_ONLY">'
    + `<hp:margin header="${MARGIN_HEADER}" footer="${MARGIN_FOOTER}" gutter="0"`
    + ` left="${MARGIN_LEFT}" right="${MARGIN_RIGHT}" top="${MARGIN_TOP}" bottom="${MARGIN_BOTTOM}"/>`
    + '</hp:pagePr>'
    + '<hp:footNotePr>'
    + '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
    + '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
    + '<hp:noteSpacing betweenNotes="850" belowLine="567" aboveLine="850"/>'
    + '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    + '<hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>'
    + '<hp:endNotePr>'
    + '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
    + '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>'
    + '<hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
    + '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    + '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr>'
    + pageBorder + '</hp:secPr>'
    + '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1"'
    + ' sameGap="0"/></hp:ctrl>';
}

function runText(text) {
  const clean = xmlEscape(text);
  if (!clean) return '<hp:t></hp:t>';
  return '<hp:t>' + clean.split('\n').join('<hp:lineBreak/>') + '</hp:t>';
}

function sectionXml(paragraphs) {
  const parts = [XML_DECL,
    `<hs:sec xmlns:hs="${NS_SECTION}" xmlns:hp="${NS_PARA}" xmlns:hc="${NS_CORE}">`];
  paragraphs.forEach((para, index) => {
    const inner = index === 0 ? secPr() : '';
    const baseline = Math.round(para.height * 0.85);
    const spacing = Math.round(para.height * 0.6);
    const horzSize = Math.max(1000, TEXT_WIDTH - para.indent);
    parts.push(
      `<hp:p id="${index}" paraPrIDRef="${para.paraId}" styleIDRef="${para.styleId}"`
      + ` pageBreak="${para.pageBreak ? 1 : 0}" columnBreak="0" merged="0">`
      + `<hp:run charPrIDRef="${para.charId}">${inner}${runText(para.text)}</hp:run>`
      + '<hp:linesegarray>'
      + `<hp:lineseg textpos="0" vertpos="0" vertsize="${para.height}"`
      + ` textheight="${para.height}" baseline="${baseline}" spacing="${spacing}"`
      + ` horzpos="0" horzsize="${horzSize}" flags="393216"/>`
      + '</hp:linesegarray></hp:p>');
  });
  parts.push('</hs:sec>');
  return parts.join('');
}

/** 문서 모델 → .hwpx 바이트 */
export async function buildHwpx(doc, options = {}) {
  const opts = {
    fontKorean: '맑은 고딕', fontLatin: '맑은 고딕',
    fontSize: 11, lineSpacing: 1.6, pageBreak: true, ...options,
  };
  const paragraphs = collectParagraphs(doc, opts);
  const preview = doc.pages.map((p) => p.blocks.map((b) => b.text).join('\n\n')).join('\n\n');

  return makeZip([
    // mimetype 은 반드시 첫 항목이고 압축하지 않아야 한다.
    { name: 'mimetype', data: MIMETYPE, store: true },
    { name: 'version.xml', data: versionXml() },
    { name: 'META-INF/container.xml', data: containerXml() },
    { name: 'META-INF/manifest.xml', data: manifestXml() },
    { name: 'META-INF/container.rdf', data: containerRdf() },
    { name: 'Contents/content.hpf', data: contentHpf(doc.title || 'scan2doc') },
    { name: 'Contents/header.xml', data: headerXml(opts) },
    { name: 'Contents/section0.xml', data: sectionXml(paragraphs) },
    { name: 'settings.xml', data: settingsXml() },
    { name: 'Preview/PrvText.txt', data: preview.slice(0, 4000) },
  ]);
}

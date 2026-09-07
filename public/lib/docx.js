// Word 문서(.docx) 만들기 — 외부 라이브러리 없이 OOXML 을 직접 쓴다.
//
// 한글이 깨지지 않으려면 글꼴을 w:rFonts 의 eastAsia 속성으로도 지정해야 한다.
// 목록은 numbering.xml 대신 기호를 본문 글자로 넣고 들여쓴다. hwpx 쪽과 결과가
// 같아 보이고, 번호 매기기 정의가 어긋나 문서가 깨질 여지가 없다.

import { makeZip, xmlEscape } from './zip.js';

const XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
const PKG_REL = 'http://schemas.openxmlformats.org/package/2006/relationships';
const OFFICE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';

const HEADING_SCALE = { 1: 1.65, 2: 1.35, 3: 1.15 };

// A4 (twip = 1/1440인치)
const PAGE_W = 11906, PAGE_H = 16838;
const MARGIN_X = 1701;   // 30mm
const MARGIN_TOP = 1134; // 20mm
const MARGIN_BOTTOM = 850;
const LIST_INDENT = 567; // 10mm

/** twip 로 바꾼 글자 크기(half-point). */
const halfPoint = (pt) => Math.round(pt * 2);

function runXml(text, { size, bold, fontKorean, fontLatin }) {
  const fonts = `<w:rFonts w:ascii="${xmlEscape(fontLatin)}" w:hAnsi="${xmlEscape(fontLatin)}"`
    + ` w:eastAsia="${xmlEscape(fontKorean)}" w:cs="${xmlEscape(fontLatin)}"/>`;
  const props = `<w:rPr>${fonts}${bold ? '<w:b/><w:bCs/>' : ''}`
    + `<w:sz w:val="${halfPoint(size)}"/><w:szCs w:val="${halfPoint(size)}"/></w:rPr>`;
  // 문단 안의 줄바꿈은 <w:br/> 로 옮긴다.
  const pieces = String(text).split('\n');
  const body = pieces
    .map((piece) => `<w:t xml:space="preserve">${xmlEscape(piece)}</w:t>`)
    .join('<w:br/>');
  return `<w:r>${props}${body}</w:r>`;
}

function paragraphXml(text, opts) {
  const {
    size, bold = false, align = 'both', indent = 0,
    spaceBefore = 0, spaceAfter = 120, lineSpacing, fontKorean, fontLatin,
  } = opts;
  const line = Math.round(lineSpacing * 240);
  const pPr = '<w:pPr>'
    + (indent ? `<w:ind w:left="${indent}" w:hanging="${indent}"/>` : '')
    + `<w:spacing w:before="${spaceBefore}" w:after="${spaceAfter}"`
    + ` w:line="${line}" w:lineRule="auto"/>`
    + `<w:jc w:val="${align}"/>`
    + '</w:pPr>';
  return `<w:p>${pPr}${runXml(text, { size, bold, fontKorean, fontLatin })}</w:p>`;
}

const pageBreakXml = () => '<w:p><w:r><w:br w:type="page"/></w:r></w:p>';

function documentXml(doc, options) {
  const { fontSize, lineSpacing, fontKorean, fontLatin, pageBreak } = options;
  const common = { lineSpacing, fontKorean, fontLatin };
  const parts = [];

  if (doc.title) {
    parts.push(paragraphXml(doc.title, {
      ...common, size: fontSize * 1.8, bold: true, align: 'center',
      spaceAfter: 360,
    }));
  }

  doc.pages.forEach((page, index) => {
    if (index > 0 && pageBreak) parts.push(pageBreakXml());
    for (const block of page.blocks) {
      if (!block.text || !block.text.trim()) continue;
      if (block.kind === 'heading') {
        const level = Math.min(3, Math.max(1, block.level || 3));
        parts.push(paragraphXml(block.text, {
          ...common, size: fontSize * HEADING_SCALE[level], bold: true,
          align: 'left', spaceBefore: 240, spaceAfter: 120,
        }));
      } else if (block.kind === 'list_item') {
        const marker = block.listMarker || '-';
        parts.push(paragraphXml(`${marker} ${block.text}`.trim(), {
          ...common, size: fontSize, align: 'left',
          indent: LIST_INDENT * ((block.level || 0) + 1), spaceAfter: 60,
        }));
      } else {
        parts.push(paragraphXml(block.text, { ...common, size: fontSize }));
      }
    }
  });

  const sectPr = '<w:sectPr>'
    + `<w:pgSz w:w="${PAGE_W}" w:h="${PAGE_H}"/>`
    + `<w:pgMar w:top="${MARGIN_TOP}" w:right="${MARGIN_X}" w:bottom="${MARGIN_BOTTOM}"`
    + ` w:left="${MARGIN_X}" w:header="708" w:footer="708" w:gutter="0"/>`
    + '</w:sectPr>';

  return XML_DECL
    + `<w:document xmlns:w="${W}"><w:body>${parts.join('')}${sectPr}</w:body></w:document>`;
}

function stylesXml(options) {
  const { fontSize, lineSpacing, fontKorean, fontLatin } = options;
  const fonts = `<w:rFonts w:ascii="${xmlEscape(fontLatin)}" w:hAnsi="${xmlEscape(fontLatin)}"`
    + ` w:eastAsia="${xmlEscape(fontKorean)}" w:cs="${xmlEscape(fontLatin)}"/>`;
  return XML_DECL + `<w:styles xmlns:w="${W}">`
    + '<w:docDefaults><w:rPrDefault><w:rPr>'
    + fonts + `<w:sz w:val="${halfPoint(fontSize)}"/><w:szCs w:val="${halfPoint(fontSize)}"/>`
    + '</w:rPr></w:rPrDefault>'
    + '<w:pPrDefault><w:pPr>'
    + `<w:spacing w:after="120" w:line="${Math.round(lineSpacing * 240)}" w:lineRule="auto"/>`
    + '</w:pPr></w:pPrDefault></w:docDefaults>'
    + '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    + '<w:name w:val="Normal"/><w:qFormat/></w:style>'
    + '</w:styles>';
}

const contentTypesXml = () => XML_DECL
  + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
  + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
  + '<Default Extension="xml" ContentType="application/xml"/>'
  + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
  + '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
  + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
  + '</Types>';

const rootRelsXml = () => XML_DECL
  + `<Relationships xmlns="${PKG_REL}">`
  + `<Relationship Id="rId1" Type="${OFFICE_REL}/officeDocument" Target="word/document.xml"/>`
  + '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
  + '</Relationships>';

const documentRelsXml = () => XML_DECL
  + `<Relationships xmlns="${PKG_REL}">`
  + `<Relationship Id="rId1" Type="${OFFICE_REL}/styles" Target="styles.xml"/>`
  + '</Relationships>';

const corePropsXml = (title) => {
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  return XML_DECL
    + '<cp:coreProperties'
    + ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
    + ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    + ' xmlns:dcterms="http://purl.org/dc/terms/"'
    + ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    + `<dc:title>${xmlEscape(title)}</dc:title>`
    + '<dc:creator>scan2doc</dc:creator><cp:lastModifiedBy>scan2doc</cp:lastModifiedBy>'
    + `<dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created>`
    + `<dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified>`
    + '</cp:coreProperties>';
};

/** 문서 모델 → .docx 바이트 */
export async function buildDocx(doc, options = {}) {
  const opts = {
    fontKorean: '맑은 고딕', fontLatin: '맑은 고딕',
    fontSize: 11, lineSpacing: 1.6, pageBreak: true, ...options,
  };
  return makeZip([
    { name: '[Content_Types].xml', data: contentTypesXml() },
    { name: '_rels/.rels', data: rootRelsXml() },
    { name: 'docProps/core.xml', data: corePropsXml(doc.title || 'scan2doc') },
    { name: 'word/_rels/document.xml.rels', data: documentRelsXml() },
    { name: 'word/styles.xml', data: stylesXml(opts) },
    { name: 'word/document.xml', data: documentXml(doc, opts) },
  ]);
}

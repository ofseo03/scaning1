// OCR 낱말을 제목·문단·목록으로 되살린다.
// 파이썬 쪽 scan2doc/layout.py, model.py 의 규칙을 그대로 옮긴 것이다.
// 두 구현이 어긋나면 같은 사진에서 다른 문서가 나오므로 규칙을 바꿀 때는 양쪽을 함께 고쳐야 한다.

/** 글자 높이 대비 이 비율보다 간격이 넓으면 띄어쓰기로 본다. */
export const WORD_GAP_RATIO = 0.42;

const CJK_RANGES = [
  [0xac00, 0xd7a3],  // 한글 음절
  [0x1100, 0x11ff],  // 한글 자모
  [0x3130, 0x318f],  // 호환 자모
  [0x4e00, 0x9fff],  // 한자
  [0x3040, 0x30ff],  // 가나
  [0xff00, 0xffef],  // 전각
];

export function isCjk(ch) {
  if (!ch) return false;
  const code = ch.codePointAt(0);
  return CJK_RANGES.some(([lo, hi]) => code >= lo && code <= hi);
}

export function isHangul(ch) {
  if (!ch) return false;
  const code = ch.codePointAt(0);
  return (code >= 0xac00 && code <= 0xd7a3)
    || (code >= 0x1100 && code <= 0x11ff)
    || (code >= 0x3130 && code <= 0x318f);
}

/**
 * 한 줄 안의 낱말을 잇는다.
 * 한국어에서 OCR 은 한 어절을 음절 단위로 쪼개 놓는 일이 잦다.
 * 글자 높이에 견준 가로 간격이 좁으면 같은 어절로 보고 붙인다.
 */
export function joinWords(words) {
  const real = words.filter((w) => w.text && w.text.trim());
  if (!real.length) return '';

  const heights = real.map((w) => w.h).sort((a, b) => a - b);
  const height = heights[Math.floor(heights.length / 2)] || Math.max(...heights);
  const threshold = Math.max(3, height * WORD_GAP_RATIO);

  let out = real[0].text;
  for (let i = 1; i < real.length; i++) {
    const prev = real[i - 1];
    const cur = real[i];
    const gap = cur.x - (prev.x + prev.w);
    // 한쪽이라도 붙여 쓰는 문자면 간격으로 판단한다.
    // '제1조', '5년'처럼 숫자가 어절 안에 섞이는 경우까지 살리기 위해서다.
    const touchingCjk = isCjk(prev.text.slice(-1)) || isCjk(cur.text[0]);
    if (!touchingCjk || gap >= threshold) out += ' ';
    out += cur.text;
  }
  return out.trim();
}

/**
 * 한 문단 안의 여러 줄을 자연스러운 한 문단으로 잇는다.
 * 한국어는 어절 경계에서 줄이 바뀌므로 공백을 넣고,
 * 한자·가나는 붙이며, 영어의 분철 하이픈은 되돌린다.
 */
export function joinLines(lines) {
  let out = '';
  for (const raw of lines) {
    const piece = (raw || '').trim();
    if (!piece) continue;
    if (!out) { out = piece; continue; }
    const prev = out.slice(-1);
    const next = piece[0];
    if (prev === '-' && /\p{L}/u.test(next) && !isCjk(next)) {
      out = out.slice(0, -1) + piece;             // 분철된 영단어 복원
    } else if (isCjk(prev) && isCjk(next) && !(isHangul(prev) || isHangul(next))) {
      out += piece;                               // 한자·가나는 붙여 쓴다
    } else {
      out += ' ' + piece;
    }
  }
  return out;
}

const BULLET_CHARS = '-–—•·‣▪▫◦○●■□▶＊*';
const BULLET_RE = new RegExp(`^\\s*([${BULLET_CHARS.replace(/[-\\\]]/g, '\\$&')}])\\s+(?=\\S)`);
const ORDERED_RES = [
  /^\s*(\(?\d{1,3}[.)])\s+(?=\S)/,          // 1. / 1) / (1)
  /^\s*([①-⑳㉑-㉟])\s*(?=\S)/,  // ① ② …
  /^\s*([가-힣][.)])\s+(?=\S)/,             // 가. 나) …
  /^\s*(\(?[ivxIVX]{1,4}[.)])\s+(?=\S)/,    // i. ii) …
  /^\s*([A-Za-z][.)])\s+(?=\S)/,            // A. b) …
];

/** 글머리 기호·번호를 떼어낸다. → { marker, rest, ordered } 또는 null */
export function splitListMarker(text) {
  const bullet = BULLET_RE.exec(text);
  if (bullet) {
    return { marker: bullet[1], rest: text.slice(bullet[0].length).trim(), ordered: false };
  }
  for (const re of ORDERED_RES) {
    const m = re.exec(text);
    if (m) {
      const rest = text.slice(m[0].length).trim();
      if (rest) return { marker: m[1], rest, ordered: true };
    }
  }
  return null;
}

const HEADING_RATIO_L3 = 1.22;
const HEADING_RATIO_L2 = 1.45;
const HEADING_RATIO_L1 = 1.8;
const HEADING_MAX_CHARS = 90;

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

/**
 * 낱말 목록 → 문단 블록 목록.
 * words: [{ text, x, y, w, h, conf, block, par, line, lineText }]
 */
export function buildBlocks(words, options = {}) {
  const {
    detectHeadings = true,
    detectLists = true,
    keepLineBreaks = false,
  } = options;

  // 1) (블록, 문단, 줄) 번호로 줄을 묶는다.
  const lineMap = new Map();
  const order = [];
  for (const w of words) {
    if (!w.text || !w.text.trim()) continue;
    const key = `${w.block}/${w.par}/${w.line}`;
    if (!lineMap.has(key)) {
      lineMap.set(key, { words: [], parKey: `${w.block}/${w.par}`, lineText: w.lineText ?? null });
      order.push(key);
    }
    lineMap.get(key).words.push(w);
  }
  const lines = order.map((key) => {
    const line = lineMap.get(key);
    // 엔진이 알려 준 줄 문장이 있으면 그대로 쓴다(띄어쓰기가 이미 맞다).
    line.text = line.lineText != null ? line.lineText.trim() : joinWords(line.words);
    line.height = median(line.words.filter((w) => w.text.trim()).map((w) => w.h));
    line.x = Math.min(...line.words.map((w) => w.x));
    return line;
  }).filter((line) => line.text);

  if (!lines.length) return [];

  // 2) 문단으로 묶는다. 글머리 기호로 시작하는 줄은 언제나 새 항목으로 끊는다.
  let blocks = [];
  if (keepLineBreaks) {
    blocks = lines.map((line) => ({ lines: [line] }));
  } else {
    let current = null;
    let currentKey = null;
    for (const line of lines) {
      const startsItem = splitListMarker(line.text) !== null;
      if (!current || line.parKey !== currentKey || startsItem) {
        current = { lines: [] };
        blocks.push(current);
        currentKey = line.parKey;
      }
      current.lines.push(line);
    }
  }

  blocks = blocks.map((block) => ({
    kind: 'paragraph',
    level: 0,
    listMarker: '',
    ordered: false,
    lines: block.lines,
    text: joinLines(block.lines.map((l) => l.text)),
    height: median(block.lines.map((l) => l.height).filter(Boolean)),
    x: Math.min(...block.lines.map((l) => l.x)),
  })).filter((block) => block.text.trim());

  if (detectHeadings) applyHeadings(blocks);
  if (detectLists) applyLists(blocks);
  return blocks;
}

/** 본문 글자 크기와 비교해 제목을 찾는다. */
export function applyHeadings(blocks) {
  const heights = blocks.flatMap((b) => b.lines.map((l) => l.height)).filter((h) => h > 0);
  if (heights.length < 3) return blocks;
  const body = median(heights);
  if (body <= 0) return blocks;

  for (const block of blocks) {
    if (block.lines.length > 2) continue;             // 여러 줄은 본문일 가능성이 높다
    const text = block.text.trim();
    if (!text || text.length > HEADING_MAX_CHARS) continue;
    if (!block.height) continue;
    const ratio = block.height / body;
    if (ratio >= HEADING_RATIO_L1) { block.kind = 'heading'; block.level = 1; }
    else if (ratio >= HEADING_RATIO_L2) { block.kind = 'heading'; block.level = 2; }
    else if (ratio >= HEADING_RATIO_L3) { block.kind = 'heading'; block.level = 3; }
  }
  return blocks;
}

/** 글머리 기호로 시작하는 문단을 목록 항목으로 표시한다. */
export function applyLists(blocks) {
  for (const block of blocks) {
    if (block.kind === 'heading') continue;
    const parsed = splitListMarker(block.text.trim());
    if (!parsed) continue;
    block.kind = 'list_item';
    block.listMarker = parsed.marker;
    block.ordered = parsed.ordered;
    block.text = parsed.rest;
  }
  return blocks;
}

/** 구조 없이 텍스트만 있을 때(폴백) 빈 줄을 문단 경계로 삼는다. */
export function blocksFromText(text, options = {}) {
  const chunks = String(text || '').split(/\n\s*\n/);
  const blocks = [];
  for (const chunk of chunks) {
    const lines = chunk.split('\n').map((l) => l.trim()).filter(Boolean);
    if (!lines.length) continue;
    blocks.push({
      kind: 'paragraph',
      level: 0,
      listMarker: '',
      ordered: false,
      lines: lines.map((t) => ({ text: t, height: 0, x: 0 })),
      text: options.keepLineBreaks ? lines.join('\n') : joinLines(lines),
      height: 0,
      x: 0,
    });
  }
  if (options.detectLists !== false) applyLists(blocks);
  return blocks;
}

// 입력 파일을 '쪽의 나열'로 바꾼다.
// 사진은 캔버스로 옮겨 보정하고, PDF 는 글자 레이어가 있으면 그대로 뽑고
// 없으면 이미지로 그려 OCR 로 넘긴다.

import { joinLines, applyLists } from './layout.js';

const PDFJS_URL = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.min.mjs';
const PDFJS_WORKER = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.worker.min.mjs';

/** PDF 한 쪽에서 이 정도 글자가 나오면 '텍스트 레이어가 있다'고 본다. */
const PDF_TEXT_MIN_CHARS = 24;

export const IMAGE_TYPES = /\.(jpe?g|png|bmp|gif|tiff?|webp|avif)$/i;
export const PDF_TYPE = /\.pdf$/i;

let pdfjsPromise = null;

async function loadPdfjs() {
  if (pdfjsPromise) return pdfjsPromise;
  pdfjsPromise = (async () => {
    try {
      const lib = await import(/* @vite-ignore */ PDFJS_URL);
      lib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
      return lib;
    } catch (err) {
      throw new Error('PDF 처리기(pdf.js)를 내려받지 못했습니다. 인터넷 연결을 확인해 주세요.');
    }
  })();
  return pdfjsPromise;
}

// --- 이미지 보정 ---------------------------------------------------------

const UPSCALE_MIN_WIDTH = 1000;
const UPSCALE_TARGET_WIDTH = 1800;

/** Otsu 방법으로 이진화 임계값을 고른다. */
function otsuThreshold(histogram, total) {
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * histogram[i];
  let sumB = 0, wB = 0, best = 0, threshold = 128;
  for (let t = 0; t < 256; t++) {
    wB += histogram[t];
    if (!wB) continue;
    const wF = total - wB;
    if (!wF) break;
    sumB += t * histogram[t];
    const mB = sumB / wB;
    const mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > best) { best = between; threshold = t; }
  }
  return threshold;
}

/**
 * 캔버스를 OCR 이 읽기 좋게 다듬는다.
 * 회색조로 바꾸고 명암을 넓힌다. binarize 를 켜면 흑백으로 자른다.
 */
export function enhanceCanvas(canvas, { grayscale = true, binarize = false } = {}) {
  if (!grayscale && !binarize) return canvas;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = image.data;
  const histogram = new Uint32Array(256);
  const gray = new Uint8ClampedArray(data.length / 4);

  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    const g = (data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) | 0;
    gray[p] = g;
    histogram[g]++;
  }

  let low = 0, high = 255;
  if (!binarize) {
    // 자동 명암(양 끝 0.5% 는 잘라 낸다)
    const total = gray.length;
    const cut = total * 0.005;
    let acc = 0;
    for (let i = 0; i < 256; i++) { acc += histogram[i]; if (acc > cut) { low = i; break; } }
    acc = 0;
    for (let i = 255; i >= 0; i--) { acc += histogram[i]; if (acc > cut) { high = i; break; } }
    if (high <= low) { low = 0; high = 255; }
  }
  const threshold = binarize ? otsuThreshold(histogram, gray.length) : 0;
  const span = high - low || 1;

  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    const value = binarize
      ? (gray[p] > threshold ? 255 : 0)
      : Math.max(0, Math.min(255, ((gray[p] - low) * 255) / span));
    data[i] = data[i + 1] = data[i + 2] = value;
    data[i + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

function makeCanvas(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width));
  canvas.height = Math.max(1, Math.round(height));
  return canvas;
}

async function bitmapFromFile(file) {
  if (typeof createImageBitmap === 'function') {
    try { return await createImageBitmap(file); } catch { /* 아래로 */ }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error(`이미지를 열 수 없습니다: ${file.name}`));
      img.src = url;
    });
    return img;
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

async function pagesFromImage(file, options) {
  const bitmap = await bitmapFromFile(file);
  const width = bitmap.width || bitmap.naturalWidth;
  const height = bitmap.height || bitmap.naturalHeight;

  // 글씨가 작으면 확대해서 인식률을 높인다.
  const scale = width < UPSCALE_MIN_WIDTH ? UPSCALE_TARGET_WIDTH / width : 1;
  const canvas = makeCanvas(width * scale, height * scale);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingQuality = 'high';
  // 투명한 부분은 흰 종이로 채운다. 빈 캔버스에 그대로 그리면 투명한 자리가
  // 검게 남아(회색조로 바꿀 때 0이 된다) 그 위의 검은 글자가 묻혀 버린다.
  // 창 모서리가 둥근 화면 캡처 PNG 에서 특히 자주 일어난다.
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  if (bitmap.close) bitmap.close();

  enhanceCanvas(canvas, options);
  return [{ kind: 'image', canvas, source: file.name, pageNo: 1 }];
}

/** PDF 글자 레이어를 문단으로 바꾼다. 글자 크기를 알아 제목 판별이 정확하다. */
function blocksFromTextContent(content, options) {
  const items = (content.items || []).filter((i) => i.str && i.str.trim());
  if (!items.length) return null;

  // 세로 위치로 줄을 묶는다.
  const rows = [];
  for (const item of items) {
    const y = Math.round(item.transform[5]);
    const x = item.transform[4];
    const size = Math.abs(item.transform[3]) || item.height || 0;
    let row = rows.find((r) => Math.abs(r.y - y) <= Math.max(2, size * 0.4));
    if (!row) { row = { y, items: [] }; rows.push(row); }
    row.items.push({ x, size, str: item.str });
  }
  rows.sort((a, b) => b.y - a.y);                       // PDF 좌표는 아래가 0
  const lines = rows.map((row) => {
    row.items.sort((a, b) => a.x - b.x);
    return {
      text: row.items.map((i) => i.str).join('').replace(/\s+/g, ' ').trim(),
      size: Math.max(...row.items.map((i) => i.size)),
    };
  }).filter((l) => l.text);
  if (!lines.length) return null;

  const sizes = lines.map((l) => l.size).filter(Boolean).sort((a, b) => a - b);
  const bodySize = sizes[Math.floor(sizes.length / 2)] || 0;

  // 크기가 비슷하고 이어지는 줄을 한 문단으로 묶는다.
  const blocks = [];
  let current = null;
  for (const line of lines) {
    const ratio = bodySize ? line.size / bodySize : 1;
    const isHeading = options.detectHeadings !== false && ratio >= 1.22 && line.text.length <= 90;
    if (isHeading) {
      blocks.push({
        kind: 'heading',
        level: ratio >= 1.8 ? 1 : ratio >= 1.45 ? 2 : 3,
        listMarker: '', ordered: false, text: line.text, lines: [line],
      });
      current = null;
      continue;
    }
    if (!current) {
      current = { kind: 'paragraph', level: 0, listMarker: '', ordered: false, lines: [] };
      blocks.push(current);
    }
    current.lines.push(line);
  }
  for (const block of blocks) {
    if (block.kind === 'paragraph') {
      block.text = options.keepLineBreaks
        ? block.lines.map((l) => l.text).join('\n')
        : joinLines(block.lines.map((l) => l.text));
    }
  }
  const kept = blocks.filter((b) => b.text && b.text.trim());
  if (options.detectLists !== false) applyLists(kept);
  return kept;
}

async function pagesFromPdf(file, options) {
  const pdfjs = await loadPdfjs();
  const buffer = await file.arrayBuffer();
  const pdf = await pdfjs.getDocument({ data: buffer }).promise;
  const pages = [];
  const wanted = options.pageFilter || (() => true);

  for (let n = 1; n <= pdf.numPages; n++) {
    if (!wanted(n, pdf.numPages)) continue;
    const page = await pdf.getPage(n);

    if (options.pdfText !== 'never') {
      let blocks = null;
      try {
        blocks = blocksFromTextContent(await page.getTextContent(), options);
      } catch { blocks = null; }
      const chars = blocks ? blocks.reduce((sum, b) => sum + b.text.length, 0) : 0;
      if (blocks && (options.pdfText === 'always' || chars >= PDF_TEXT_MIN_CHARS)) {
        pages.push({ kind: 'text', blocks, source: file.name, pageNo: n });
        continue;                                       // OCR 이 필요 없다
      }
    }

    const scale = (options.dpi || 300) / 72;
    const viewport = page.getViewport({ scale });
    const canvas = makeCanvas(viewport.width, viewport.height);
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: ctx, viewport }).promise;
    enhanceCanvas(canvas, options);
    pages.push({ kind: 'image', canvas, source: file.name, pageNo: n });
  }
  await pdf.destroy();
  return pages;
}

/** 파일 하나 → 쪽 목록 */
export async function pagesFromFile(file, options = {}) {
  if (PDF_TYPE.test(file.name) || file.type === 'application/pdf') {
    return pagesFromPdf(file, options);
  }
  if (IMAGE_TYPES.test(file.name) || (file.type || '').startsWith('image/')) {
    return pagesFromImage(file, options);
  }
  throw new Error(`지원하지 않는 형식입니다: ${file.name}`);
}

/** '1-3,7' 형식을 판별 함수로 바꾼다. */
export function pageFilterFrom(spec) {
  const text = String(spec || '').trim();
  if (!text) return null;
  const parts = text.split(',').map((s) => s.trim()).filter(Boolean);
  return (pageNo, total) => parts.some((part) => {
    if (part.includes('-')) {
      const [a, b] = part.split('-');
      let start = a.trim() ? parseInt(a, 10) : 1;
      let end = b.trim() ? parseInt(b, 10) : total;
      if (start > end) [start, end] = [end, start];
      return pageNo >= start && pageNo <= end;
    }
    return pageNo === parseInt(part, 10);
  });
}

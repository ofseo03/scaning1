// 브라우저에서 도는 OCR — tesseract.js(WASM)를 감싼다.
//
// 서버가 필요 없다. 사진과 학습 데이터가 모두 브라우저 안에 머물기 때문에
// 파일이 어디로도 올라가지 않는다는 뜻이기도 하다.
//
// tesseract.js 는 버전에 따라 결과 모양이 조금씩 다르다. blocks 계층이 있으면
// 그것을 쓰고, 없으면 옛 모양(paragraphs/lines/words)을, 그마저 없으면 평문만 쓴다.

const TESSERACT_URL = 'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js';

let tesseractPromise = null;

/** tesseract.js 를 한 번만 내려받는다. */
function loadTesseract() {
  if (window.Tesseract) return Promise.resolve(window.Tesseract);
  if (tesseractPromise) return tesseractPromise;
  tesseractPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = TESSERACT_URL;
    script.onload = () => window.Tesseract
      ? resolve(window.Tesseract)
      : reject(new Error('tesseract.js 를 불러왔지만 초기화되지 않았습니다.'));
    script.onerror = () => reject(new Error(
      'OCR 엔진(tesseract.js)을 내려받지 못했습니다. 인터넷 연결을 확인해 주세요.'));
    document.head.appendChild(script);
  });
  return tesseractPromise;
}

/** bbox {x0,y0,x1,y1} → 우리 좌표 {x,y,w,h} */
const box = (b) => ({
  x: Math.round(b?.x0 ?? 0),
  y: Math.round(b?.y0 ?? 0),
  w: Math.round((b?.x1 ?? 0) - (b?.x0 ?? 0)),
  h: Math.round((b?.y1 ?? 0) - (b?.y0 ?? 0)),
});

/**
 * tesseract 결과에서 낱말 목록을 뽑는다.
 * 줄마다 엔진이 준 문장(line.text)을 함께 달아 둔다.
 * 한국어는 낱말이 음절로 쪼개지지만 줄 문장에는 띄어쓰기가 살아 있기 때문이다.
 */
export function wordsFromResult(data) {
  const words = [];
  let blockNo = 0;

  const pushLine = (line, parNo, lineNo) => {
    const lineText = (line.text || '').trim() || null;
    for (const word of line.words || []) {
      const text = (word.text || '').trim();
      if (!text) continue;
      words.push({
        text, ...box(word.bbox),
        conf: typeof word.confidence === 'number' ? word.confidence : -1,
        block: blockNo, par: parNo, line: lineNo, lineText,
      });
    }
  };

  if (Array.isArray(data?.blocks) && data.blocks.length) {
    for (const block of data.blocks) {
      blockNo += 1;
      let parNo = 0;
      for (const par of block.paragraphs || []) {
        parNo += 1;
        let lineNo = 0;
        for (const line of par.lines || []) {
          lineNo += 1;
          pushLine(line, parNo, lineNo);
        }
      }
    }
    if (words.length) return words;
  }

  // 옛 모양: 최상위 paragraphs / lines
  if (Array.isArray(data?.paragraphs) && data.paragraphs.length) {
    blockNo = 1;
    let parNo = 0;
    for (const par of data.paragraphs) {
      parNo += 1;
      let lineNo = 0;
      for (const line of par.lines || []) {
        lineNo += 1;
        pushLine(line, parNo, lineNo);
      }
    }
    if (words.length) return words;
  }
  if (Array.isArray(data?.lines) && data.lines.length) {
    blockNo = 1;
    data.lines.forEach((line, index) => pushLine(line, 1, index + 1));
  }
  return words;
}

export function averageConfidence(words) {
  const scored = words.filter((w) => w.conf >= 0).map((w) => w.conf);
  return scored.length ? scored.reduce((a, b) => a + b, 0) / scored.length : -1;
}

/**
 * OCR 일꾼을 만든다.
 * psm 4(변동 글자 크기의 한 단 문서)가 한국어 문서에서 3(전체 자동)보다 훨씬 안정적이라
 * 이것을 기본값으로 둔다. 파이썬 쪽에서 실제 사진으로 확인한 결과다.
 */
export async function createRecognizer({ language = 'kor+eng', psm = '4', onProgress } = {}) {
  const Tesseract = await loadTesseract();
  const worker = await Tesseract.createWorker(language, 1, {
    logger: (m) => {
      if (onProgress && typeof m.progress === 'number') onProgress(m.status, m.progress);
    },
  });
  await worker.setParameters({
    tessedit_pageseg_mode: String(psm),
    preserve_interword_spaces: '1',
  });

  return {
    async recognize(image) {
      let data;
      try {
        ({ data } = await worker.recognize(image, {}, { blocks: true, text: true }));
      } catch {
        ({ data } = await worker.recognize(image));   // 옛 버전은 출력 옵션을 안 받는다
      }
      const words = wordsFromResult(data);
      return { words, text: data?.text || '', confidence: averageConfidence(words) };
    },
    terminate: () => worker.terminate(),
  };
}

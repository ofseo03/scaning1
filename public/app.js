// scan2doc 브라우저판 — 서버 없이 이 화면 안에서 변환을 끝낸다.
//
// 흐름: 파일 → 쪽(캔버스 또는 PDF 글자) → OCR → 구조 복원 → 문서 만들기 → 내려받기

import { pagesFromFile, pageFilterFrom } from './lib/source.js';
import { createRecognizer } from './lib/ocr.js';
import { buildBlocks, blocksFromText } from './lib/layout.js';
import { buildHwpx } from './lib/hwpx.js';
import { buildDocx } from './lib/docx.js';
import { buildText, buildMarkdown } from './lib/text.js';

const FORMATS = [
  { id: 'docx', label: 'Word (.docx)', ext: '.docx', on: true,
    mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
  { id: 'hwpx', label: '한글 (.hwpx)', ext: '.hwpx', on: true,
    mime: 'application/hwp+zip' },
  { id: 'txt', label: '텍스트 (.txt)', ext: '.txt', on: false, mime: 'text/plain' },
  { id: 'md', label: '마크다운 (.md)', ext: '.md', on: false, mime: 'text/markdown' },
];

const $ = (id) => document.getElementById(id);
const el = {
  notice: $('notice'), drop: $('drop'), picker: $('picker'), filelist: $('filelist'),
  formats: $('formats'), run: $('run'), reset: $('reset'), status: $('status'),
  progress: document.querySelector('.progress'), bar: document.querySelector('.progress > i'),
  resultCard: $('resultCard'), results: $('results'), preview: $('preview'),
};

const state = { files: [], busy: false, urls: [] };

// --- 화면 ---------------------------------------------------------------

function notify(message, kind = 'err') {
  if (!message) { el.notice.hidden = true; return; }
  el.notice.textContent = message;
  el.notice.className = `notice ${kind}`;
  el.notice.hidden = false;
}

function setStatus(text) { el.status.textContent = text || ''; }

function setProgress(ratio) {
  if (ratio == null) { el.progress.hidden = true; return; }
  el.progress.hidden = false;
  el.bar.style.width = `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`;
}

function renderFormats() {
  el.formats.innerHTML = '';
  for (const format of FORMATS) {
    const label = document.createElement('label');
    label.className = `chip${format.on ? ' on' : ''}`;
    label.innerHTML = `<input type="checkbox" ${format.on ? 'checked' : ''}>` +
      `<span>${format.label}</span>`;
    const input = label.querySelector('input');
    input.addEventListener('change', () => {
      format.on = input.checked;
      label.classList.toggle('on', format.on);
      refresh();
    });
    el.formats.appendChild(label);
  }
}

const prettySize = (bytes) => bytes > 1024 * 1024
  ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
  : `${Math.max(1, Math.round(bytes / 1024))} KB`;

function renderFiles() {
  el.filelist.innerHTML = '';
  state.files.forEach((file, index) => {
    const li = document.createElement('li');
    const name = document.createElement('span');
    name.textContent = file.name;
    const size = document.createElement('span');
    size.className = 'hint';
    size.textContent = prettySize(file.size);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.setAttribute('aria-label', `${file.name} 빼기`);
    remove.textContent = '✕';
    remove.addEventListener('click', () => {
      state.files.splice(index, 1);
      renderFiles();
      refresh();
    });
    li.append(name, size, remove);
    el.filelist.appendChild(li);
  });
}

function refresh() {
  el.run.disabled = state.busy || !state.files.length || !FORMATS.some((f) => f.on);
}

function addFiles(list) {
  for (const file of list) {
    if (!state.files.some((f) => f.name === file.name && f.size === file.size)) {
      state.files.push(file);
    }
  }
  renderFiles();
  refresh();
}

// --- 옵션 읽기 -----------------------------------------------------------

function readOptions() {
  return {
    language: $('language').value,
    psm: $('psm').value,
    dpi: parseInt($('dpi').value, 10) || 300,
    title: $('title').value.trim(),
    merge: $('merge').checked,
    binarize: $('binarize').checked,
    grayscale: true,
    keepLineBreaks: $('keepLineBreaks').checked,
    detectHeadings: !$('noHeadings').checked,
    detectLists: !$('noLists').checked,
    pageBreak: true,
    pageFilter: pageFilterFrom($('pages').value),
    pdfText: 'auto',
    fontKorean: '맑은 고딕',
    fontLatin: '맑은 고딕',
    fontSize: 11,
    lineSpacing: 1.6,
  };
}

// --- 변환 ---------------------------------------------------------------

const baseName = (name) => name.replace(/\.[^.]+$/, '');

async function buildOutputs(doc, options) {
  const outputs = [];
  for (const format of FORMATS.filter((f) => f.on)) {
    let bytes;
    if (format.id === 'docx') bytes = await buildDocx(doc, options);
    else if (format.id === 'hwpx') bytes = await buildHwpx(doc, options);
    else if (format.id === 'txt') bytes = buildText(doc);
    else bytes = buildMarkdown(doc, options);
    outputs.push({ name: `${doc.name}${format.ext}`, bytes, mime: format.mime });
  }
  return outputs;
}

function showResults(outputs, docs) {
  el.results.innerHTML = '';
  for (const url of state.urls) URL.revokeObjectURL(url);
  state.urls = [];

  for (const output of outputs) {
    const blob = new Blob([output.bytes], { type: output.mime });
    const url = URL.createObjectURL(blob);
    state.urls.push(url);

    const li = document.createElement('li');
    const link = document.createElement('a');
    link.className = 'name';
    link.href = url;
    link.download = output.name;
    link.textContent = output.name;
    const meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = prettySize(output.bytes.length ?? output.bytes.byteLength);
    li.append(link, meta);
    el.results.appendChild(li);
  }

  el.preview.value = docs
    .map((doc) => doc.pages.map((p) => p.blocks.map((b) => b.text).join('\n\n')).join('\n\n'))
    .join('\n\n──────────\n\n');
  el.resultCard.hidden = false;
}

async function run() {
  if (state.busy) return;
  state.busy = true;
  refresh();
  notify('');
  setProgress(0);

  const options = readOptions();
  let recognizer = null;
  const confidences = [];

  try {
    // 1) 모든 파일을 쪽으로 펼친다.
    setStatus('파일을 읽는 중…');
    const loaded = [];
    for (const file of state.files) {
      const pages = await pagesFromFile(file, options);
      loaded.push({ file, pages });
    }
    const totalPages = loaded.reduce((n, item) => n + item.pages.length, 0);
    if (!totalPages) throw new Error('읽을 수 있는 쪽이 없습니다. 쪽 범위를 확인해 주세요.');

    // 2) OCR 이 필요한 쪽이 하나라도 있으면 엔진을 띄운다.
    const needsOcr = loaded.some((item) => item.pages.some((p) => p.kind === 'image'));
    if (needsOcr) {
      setStatus('글자 인식 엔진을 준비하는 중… (처음 한 번은 학습 데이터를 내려받습니다)');
      recognizer = await createRecognizer({
        language: options.language,
        psm: options.psm,
        onProgress: (status, ratio) => {
          if (status === 'loading language traineddata' || status === 'loading tesseract core') {
            setStatus(`엔진 준비 중… ${Math.round(ratio * 100)}%`);
          }
        },
      });
    }

    // 3) 쪽마다 인식한다.
    let done = 0;
    const docs = [];
    const merged = { name: '', title: options.title, pages: [] };

    for (const item of loaded) {
      const doc = { name: baseName(item.file.name), title: options.title, pages: [] };
      for (const page of item.pages) {
        done += 1;
        setStatus(`${item.file.name} · ${page.pageNo}쪽 인식 중… (${done}/${totalPages})`);
        setProgress(done / totalPages);

        let blocks;
        if (page.kind === 'text') {
          blocks = page.blocks;                       // PDF 글자 레이어 — OCR 불필요
        } else {
          const result = await recognizer.recognize(page.canvas);
          if (result.confidence >= 0) confidences.push(result.confidence);
          blocks = result.words.length
            ? buildBlocks(result.words, options)
            : blocksFromText(result.text, options);
        }
        (options.merge ? merged : doc).pages.push({ blocks });
      }
      if (!options.merge) docs.push(doc);
    }

    if (options.merge) {
      merged.name = state.files.length > 1
        ? `${baseName(state.files[0].name)}_외${state.files.length - 1}건`
        : baseName(state.files[0].name);
      docs.push(merged);
    }

    // 4) 문서를 만든다.
    setStatus('문서를 만드는 중…');
    const outputs = [];
    for (const doc of docs) outputs.push(...await buildOutputs(doc, options));

    setProgress(1);
    showResults(outputs, docs);

    const average = confidences.length
      ? confidences.reduce((a, b) => a + b, 0) / confidences.length : -1;
    const score = average >= 0 ? ` · 인식 신뢰도 ${average.toFixed(0)}%` : '';
    setStatus(`끝났습니다. ${totalPages}쪽${score}`);
    if (average >= 0 && average < 70) {
      notify('인식률이 낮습니다. ‘흑백 이진화’를 켜거나 더 밝고 선명한 사진으로 다시 해 보세요.', 'warn');
    }
  } catch (error) {
    console.error(error);
    setProgress(null);
    setStatus('');
    notify(error?.message || '변환에 실패했습니다.');
  } finally {
    if (recognizer) { try { await recognizer.terminate(); } catch { /* 무시 */ } }
    state.busy = false;
    refresh();
  }
}

// --- 이벤트 연결 ---------------------------------------------------------

function wire() {
  renderFormats();
  refresh();

  el.drop.addEventListener('click', () => el.picker.click());
  el.drop.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.picker.click(); }
  });
  el.picker.addEventListener('change', () => {
    addFiles(el.picker.files);
    el.picker.value = '';
  });

  for (const type of ['dragenter', 'dragover']) {
    el.drop.addEventListener(type, (e) => {
      e.preventDefault();
      el.drop.classList.add('over');
    });
  }
  for (const type of ['dragleave', 'drop']) {
    el.drop.addEventListener(type, (e) => {
      e.preventDefault();
      el.drop.classList.remove('over');
    });
  }
  el.drop.addEventListener('drop', (e) => {
    if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
  });
  // 창 밖으로 파일을 떨어뜨렸을 때 브라우저가 파일을 여는 것을 막는다.
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());

  el.run.addEventListener('click', run);
  el.reset.addEventListener('click', () => {
    state.files = [];
    renderFiles();
    refresh();
    el.resultCard.hidden = true;
    setStatus('');
    setProgress(null);
    notify('');
  });

  if (typeof CompressionStream === 'undefined') {
    notify('이 브라우저는 오래되어 문서 압축을 지원하지 않습니다. 최신 Chrome·Edge·Safari·Firefox 를 써 주세요.', 'warn');
  }
}

wire();

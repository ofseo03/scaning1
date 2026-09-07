/* scan2doc 웹 화면의 동작.
 *
 * 흐름은 서버와 같다. 파일을 모아 /api/jobs 로 올리고, 돌아온 작업 번호로
 * 진행 상황을 물어보다가, 끝나면 내려받기 단추를 만든다.
 * 라이브러리는 쓰지 않는다(오프라인 설치에서도 그대로 돌아가야 한다).
 */
"use strict";

const $ = (id) => document.getElementById(id);
const POLL_MS = 800;          // 진행 상황을 물어보는 간격
const CONFIDENCE_WARN = 70;   // 이보다 낮으면 다시 찍으라고 안내한다

const state = {
  files: [],      // 사용자가 고른 File 객체들
  config: null,   // /api/config 응답
  jobId: null,
  timer: null,
};

/* --- 시작 ------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
  bindDropZone();
  bindButtons();
  loadConfig();
  registerServiceWorker();
});

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) throw new Error(`설정을 받지 못했습니다 (HTTP ${res.status})`);
    state.config = await res.json();
    renderFormats(state.config);
    renderLanguages(state.config);
    renderLimits(state.config);
  } catch (err) {
    notice(`서버와 연결하지 못했습니다: ${err.message}`);
  }
}

function renderFormats(config) {
  const box = $("formats");
  box.textContent = "";
  config.formats.forEach((fmt) => {
    const on = config.default_formats.includes(fmt.name);
    const label = document.createElement("label");
    label.className = "chip" + (on ? " on" : "");
    label.title = fmt.description;

    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = fmt.name;
    input.checked = on;
    input.addEventListener("change", () => {
      label.classList.toggle("on", input.checked);
      updateConvertButton();
    });

    label.append(input, document.createTextNode(`${fmt.name} (${fmt.extension})`));
    box.append(label);
  });
}

function renderLanguages(config) {
  const select = $("language");
  select.textContent = "";
  config.languages.forEach((lang) => {
    const option = document.createElement("option");
    option.value = lang.code;
    option.textContent = `${lang.label} — ${lang.code}`;
    select.append(option);
  });
}

function renderLimits(config) {
  const { max_upload_mb, max_files, ttl_seconds } = config.limits;
  $("drop").querySelector(".drop-sub").textContent =
    `또는 눌러서 고르기 · 사진(JPG·PNG·TIFF…)과 PDF · ` +
    `${max_files}개까지, 하나에 ${max_upload_mb}MB까지`;
  $("ttlText").textContent = humanDuration(ttl_seconds);
  $("version").textContent = `· scan2doc ${config.version}`;
}

/* --- 파일 고르기 ------------------------------------------------------ */

function bindDropZone() {
  const drop = $("drop");
  const picker = $("picker");

  picker.accept = "image/*,.pdf";
  drop.addEventListener("click", () => picker.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picker.click(); }
  });
  picker.addEventListener("change", () => {
    addFiles(picker.files);
    picker.value = "";   // 같은 파일을 다시 고를 수 있게 비운다
  });

  ["dragenter", "dragover"].forEach((type) =>
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((type) =>
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
}

function addFiles(fileList) {
  const limits = state.config ? state.config.limits : { max_files: 30, max_upload_mb: 50 };
  const accept = state.config ? state.config.accept : null;

  for (const file of fileList) {
    if (state.files.length >= limits.max_files) {
      notice(`한 번에 ${limits.max_files}개까지 올릴 수 있습니다.`);
      break;
    }
    const suffix = file.name.includes(".") ? "." + file.name.split(".").pop().toLowerCase() : "";
    if (accept && !accept.includes(suffix)) {
      notice(`지원하지 않는 형식입니다: ${file.name}`);
      continue;
    }
    if (file.size > limits.max_upload_mb * 1024 * 1024) {
      notice(`파일이 너무 큽니다: ${file.name} (최대 ${limits.max_upload_mb}MB)`);
      continue;
    }
    // 이름과 크기가 같으면 같은 파일로 본다(두 번 끌어다 놓는 실수를 막는다).
    if (state.files.some((f) => f.name === file.name && f.size === file.size)) continue;
    state.files.push(file);
  }
  renderFileList();
  updateConvertButton();
}

function renderFileList() {
  const list = $("filelist");
  list.textContent = "";
  state.files.forEach((file, index) => {
    const item = document.createElement("li");

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = file.name;          // textContent — 파일 이름을 HTML로 해석하지 않는다

    const size = document.createElement("span");
    size.className = "size";
    size.textContent = humanSize(file.size);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.title = "빼기";
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      state.files.splice(index, 1);
      renderFileList();
      updateConvertButton();
    });

    item.append(name, size, remove);
    list.append(item);
  });
}

function updateConvertButton() {
  $("convert").disabled = state.files.length === 0 || pickedFormats().length === 0;
}

function pickedFormats() {
  return Array.from($("formats").querySelectorAll("input:checked")).map((i) => i.value);
}

/* --- 변환 ------------------------------------------------------------- */

function bindButtons() {
  $("convert").addEventListener("click", startConversion);
  $("reset").addEventListener("click", resetAll);
  $("doctor").addEventListener("click", runDoctor);
}

function collectOptions() {
  return {
    formats: pickedFormats(),
    hwp_format: $("hwpFormat").value,
    merge: $("merge").checked,
    title: $("title").value,
    language: $("language").value,
    psm: $("psm").value,
    dpi: Number($("dpi").value) || 300,
    pages: $("pages").value,
    keep_line_breaks: $("keepLineBreaks").checked,
    detect_headings: $("detectHeadings").checked,
    detect_lists: $("detectLists").checked,
    font_korean: $("font").value,
    font_latin: $("font").value,
    font_size: Number($("fontSize").value) || 11,
    preprocess: {
      enabled: $("preprocessEnabled").checked,
      binarize: $("binarize").checked,
      denoise: $("denoise").checked,
    },
  };
}

async function startConversion() {
  clearNotice();
  $("result").hidden = true;
  $("convert").disabled = true;
  showProgress(0.02, "파일을 올리는 중…");

  const form = new FormData();
  state.files.forEach((file) => form.append("files", file, file.name));
  form.append("options", JSON.stringify(collectOptions()));

  try {
    const res = await fetch("/api/jobs", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
    state.jobId = data.id;
    poll();
  } catch (err) {
    stopProgress();
    $("convert").disabled = false;
    notice(`변환을 시작하지 못했습니다: ${err.message}`);
  }
}

function poll() {
  clearTimeout(state.timer);
  state.timer = setTimeout(checkStatus, POLL_MS);
}

async function checkStatus() {
  if (!state.jobId) return;
  try {
    const res = await fetch(`/api/jobs/${state.jobId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const job = await res.json();
    showProgress(job.progress, job.message);

    if (job.state === "done") { finish(job); return; }
    if (job.state === "failed") { fail(job.error || "변환에 실패했습니다."); return; }
    poll();
  } catch (err) {
    fail(`진행 상황을 확인하지 못했습니다: ${err.message}`);
  }
}

function finish(job) {
  stopProgress();
  $("result").hidden = false;
  $("reset").hidden = false;
  $("convert").disabled = false;

  const confidence = job.confidence >= 0 ? `${job.confidence.toFixed(0)}%` : "-";
  const summary = $("summary");
  summary.className = "summary";
  summary.textContent =
    `${job.page_count}쪽 · 인식 신뢰도 ${confidence} · ${job.elapsed.toFixed(1)}초`;
  if (job.confidence >= 0 && job.confidence < CONFIDENCE_WARN) {
    summary.classList.add("low");
    summary.textContent += " — 흑백 이진화를 켜거나 더 선명하게 다시 찍어 보세요.";
  }

  const box = $("downloads");
  box.textContent = "";
  job.outputs.forEach((out) => {
    box.append(downloadLink(out.url, `⬇ ${out.name}`, humanSize(out.size)));
  });
  if (job.archive_url) {
    const all = downloadLink(job.archive_url, "⬇ 전체 ZIP으로");
    all.classList.add("all");
    box.append(all);
  }

  const previewBox = $("previewBox");
  previewBox.hidden = !job.preview;
  $("preview").textContent = job.preview || "";
}

function downloadLink(url, text, hint) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  link.textContent = hint ? `${text} (${hint})` : text;
  return link;
}

function fail(message) {
  stopProgress();
  $("convert").disabled = false;
  $("reset").hidden = false;
  notice(message);
}

function resetAll() {
  clearTimeout(state.timer);
  // 서버에 남은 작업 폴더를 미리 치워 준다(실패해도 TTL이 지나면 지워진다).
  if (state.jobId) {
    fetch(`/api/jobs/${state.jobId}`, { method: "DELETE" }).catch(() => {});
  }
  state.files = [];
  state.jobId = null;
  renderFileList();
  updateConvertButton();
  clearNotice();
  stopProgress();
  $("result").hidden = true;
  $("reset").hidden = true;
}

/* --- 진행 표시와 알림 -------------------------------------------------- */

function showProgress(ratio, message) {
  $("progress").hidden = false;
  $("barfill").style.width = `${Math.round((ratio || 0) * 100)}%`;
  $("progressText").textContent = message || "";
}

function stopProgress() {
  $("progress").hidden = true;
  $("barfill").style.width = "0";
}

function notice(message, kind = "error") {
  const box = $("notice");
  box.hidden = false;
  box.className = "notice" + (kind === "info" ? " info" : "");
  box.textContent = message;
}

function clearNotice() {
  $("notice").hidden = true;
  $("notice").textContent = "";
}

/* --- 환경 점검 --------------------------------------------------------- */

async function runDoctor() {
  const out = $("doctorOut");
  out.hidden = false;
  out.textContent = "점검 중…";
  try {
    const res = await fetch("/api/doctor");
    const data = await res.json();
    out.textContent = data.report;
  } catch (err) {
    out.textContent = `점검하지 못했습니다: ${err.message}`;
  }
}

/* --- 도우미 ------------------------------------------------------------ */

function humanSize(bytes) {
  if (!bytes) return "0B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)}${units[unit]}`;
}

function humanDuration(seconds) {
  if (seconds >= 3600) return `${Math.round(seconds / 3600)}시간`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}분`;
  return `${seconds}초`;
}

function registerServiceWorker() {
  // 앱으로 설치했을 때 화면 껍데기라도 바로 뜨게 한다. 실패해도 문제없다.
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

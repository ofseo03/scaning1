"""웹으로 들어온 변환 요청을 백그라운드에서 처리하는 작업 관리자.

HTTP 요청 하나에 OCR이 끝날 때까지 매달려 있으면 사진 몇 장만 올려도 응답이
몇 분씩 걸린다. 그래서 업로드 즉시 작업 번호를 돌려주고, 실제 변환은 작업자
스레드에서 돌린다. 브라우저는 번호로 진행 상황을 물어보다가 끝나면 내려받는다.

작업마다 자기만의 폴더를 하나씩 쓴다.

    <root>/<작업번호>/
    ├── uploads/   올라온 원본
    └── outputs/   변환 결과 (내려받기 대상)

폴더는 완료 후 일정 시간(TTL)이 지나면 청소 스레드가 통째로 지운다.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import IO, Iterable

from ..config import ConvertOptions
from ..errors import Scan2DocError

log = logging.getLogger(__name__)

#: 완료된 작업을 남겨 두는 기본 시간(초). 이 뒤에는 결과 파일까지 지운다.
DEFAULT_TTL = 3600

#: 동시에 돌릴 변환 개수. OCR은 CPU를 많이 쓰므로 기본값을 작게 잡는다.
DEFAULT_WORKERS = 2

#: 미리보기로 돌려줄 인식 텍스트의 최대 길이
PREVIEW_LIMIT = 4000


class JobState(str, Enum):
    """작업의 진행 상태."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


#: 사람이 읽을 상태 이름
STATE_LABELS = {
    JobState.QUEUED: "차례 기다리는 중",
    JobState.RUNNING: "변환 중",
    JobState.DONE: "완료",
    JobState.FAILED: "실패",
}


@dataclass
class OutputFile:
    """내려받을 수 있는 결과 파일 하나."""

    name: str
    path: Path
    size: int = 0

    def to_dict(self, index: int, job_id: str) -> dict:
        return {
            "index": index,
            "name": self.name,
            "size": self.size,
            "url": f"/api/jobs/{job_id}/files/{index}",
        }


@dataclass
class Job:
    """업로드 한 번에 대응하는 변환 작업."""

    id: str
    root: Path
    options: ConvertOptions
    created_at: float = field(default_factory=time.time)

    state: JobState = JobState.QUEUED
    stage: str = ""
    message: str = "차례를 기다리고 있습니다."
    progress: float = 0.0

    sources: list[str] = field(default_factory=list)
    outputs: list[OutputFile] = field(default_factory=list)
    error: str = ""

    page_count: int = 0
    confidence: float = -1.0
    elapsed: float = 0.0
    text_layer_pages: int = 0
    preview: str = ""

    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def upload_dir(self) -> Path:
        return self.root / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.root / "outputs"

    @property
    def finished(self) -> bool:
        return self.state in (JobState.DONE, JobState.FAILED)

    def to_dict(self) -> dict:
        """브라우저에 돌려줄 JSON 표현."""
        return {
            "id": self.id,
            "state": self.state.value,
            "state_label": STATE_LABELS[self.state],
            "stage": self.stage,
            "message": self.message,
            "progress": round(self.progress, 3),
            "sources": list(self.sources),
            "outputs": [out.to_dict(i, self.id) for i, out in enumerate(self.outputs)],
            "archive_url": f"/api/jobs/{self.id}/archive" if len(self.outputs) > 1 else None,
            "error": self.error,
            "page_count": self.page_count,
            "confidence": round(self.confidence, 1),
            "elapsed": round(self.elapsed, 2),
            "text_layer_pages": self.text_layer_pages,
            "preview": self.preview,
            "created_at": self.created_at,
        }


class JobStore:
    """작업을 만들고, 돌리고, 때가 되면 치운다."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        max_workers: int = DEFAULT_WORKERS,
        ttl: float = DEFAULT_TTL,
        max_jobs: int = 200,
    ) -> None:
        self._owns_root = root is None
        self.root = Path(root) if root else Path(tempfile.mkdtemp(prefix="scan2doc-web-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.max_jobs = max_jobs

        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="scan2doc-web")
        self._closed = False

    # --- 작업 만들기 -----------------------------------------------------

    def create(self, options: ConvertOptions) -> Job:
        """빈 작업과 그 작업의 폴더를 만든다. 파일은 아직 없다."""
        job_id = uuid.uuid4().hex[:16]
        job = Job(id=job_id, root=self.root / job_id, options=options)
        job.upload_dir.mkdir(parents=True, exist_ok=True)
        job.output_dir.mkdir(parents=True, exist_ok=True)
        # 결과는 반드시 이 작업의 폴더 안에만 쓴다. 브라우저가 저장 위치를
        # 정할 수 없게 여기서 못박아 둔다.
        job.options.output = job.output_dir
        with self._lock:
            self._jobs[job_id] = job
        self._trim()
        return job

    def add_upload(self, job: Job, filename: str, stream: IO[bytes], *,
                   max_bytes: int | None = None) -> Path:
        """올라온 파일 하나를 작업 폴더에 저장한다.

        같은 이름이 겹치면 번호를 붙이고, 크기 제한을 넘으면 지우고 오류를 낸다.
        """
        target = _unique_in(job.upload_dir, filename)
        written = 0
        with open(target, "wb") as out:
            while True:
                chunk = stream.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise Scan2DocError(
                        f"파일이 너무 큽니다: {filename} "
                        f"(한 번에 {max_bytes // (1 << 20)}MB까지)"
                    )
                out.write(chunk)
        if written == 0:
            target.unlink(missing_ok=True)
            raise Scan2DocError(f"빈 파일입니다: {filename}")
        job.sources.append(target.name)
        return target

    def start(self, job: Job) -> Future:
        """변환을 작업자 스레드에 맡긴다."""
        if not job.sources:
            raise Scan2DocError("변환할 파일이 없습니다.")
        return self._pool.submit(self._run, job)

    # --- 조회와 정리 -----------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        _rmtree(job.root)
        return True

    def sweep(self, now: float | None = None) -> int:
        """TTL이 지난 작업을 지운다. 지운 개수를 돌려준다."""
        now = time.time() if now is None else now
        expired = [
            job for job in self.list_jobs()
            if job.finished and job.finished_at and now - job.finished_at > self.ttl
        ]
        for job in expired:
            self.delete(job.id)
        return len(expired)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        if self._owns_root:
            _rmtree(self.root)

    def _trim(self) -> None:
        """작업 수가 한도를 넘으면 끝난 것부터 오래된 순으로 지운다."""
        with self._lock:
            if len(self._jobs) <= self.max_jobs:
                return
            finished = sorted(
                (j for j in self._jobs.values() if j.finished),
                key=lambda j: j.finished_at,
            )
            excess = len(self._jobs) - self.max_jobs
            victims = [job.id for job in finished[:excess]]
            for job_id in victims:
                self._jobs.pop(job_id, None)
        for job_id in victims:
            _rmtree(self.root / job_id)

    # --- 실제 변환 -------------------------------------------------------

    def _run(self, job: Job) -> None:
        from ..pipeline import convert  # 무거운 의존성은 실제로 돌 때 부른다

        job.state = JobState.RUNNING
        job.started_at = time.time()
        job.message = "파일을 읽고 있습니다."

        def progress(stage: str, message: str, ratio: float) -> None:
            job.stage = stage
            job.message = message
            # 0.02~0.98 사이로 눌러 둔다. 100%는 결과 파일이 준비된 뒤에만 쓴다.
            job.progress = min(0.98, max(0.02, ratio))

        try:
            inputs = sorted(job.upload_dir.iterdir())
            results = convert(inputs, job.options, progress=progress)
        except Scan2DocError as exc:
            self._fail(job, str(exc))
            return
        except Exception as exc:  # 예상 밖의 오류도 작업 하나만 실패시킨다
            log.exception("변환 실패 (job=%s)", job.id)
            self._fail(job, f"변환 중 오류가 생겼습니다: {exc}")
            return

        job.outputs = _collect_outputs(results)
        job.page_count = sum(r.page_count for r in results)
        job.elapsed = sum(r.elapsed for r in results)
        job.text_layer_pages = sum(r.text_layer_pages for r in results)
        job.confidence = _average_confidence(results)
        job.preview = _preview_text(results)

        job.state = JobState.DONE
        job.stage = "done"
        job.progress = 1.0
        job.message = f"{job.page_count}쪽 변환을 마쳤습니다."
        job.finished_at = time.time()

    def _fail(self, job: Job, message: str) -> None:
        job.state = JobState.FAILED
        job.stage = "error"
        job.error = message
        job.message = message
        job.progress = 1.0
        job.finished_at = time.time()

    # --- 결과 묶어 내려받기 ---------------------------------------------

    def archive_path(self, job: Job) -> Path:
        """결과 파일을 ZIP 하나로 묶는다(이미 있으면 그대로 쓴다)."""
        if not job.outputs:
            raise Scan2DocError("내려받을 결과가 없습니다.")
        target = job.root / f"scan2doc-{job.id}.zip"
        if target.exists():
            return target
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for out in job.outputs:
                archive.write(out.path, arcname=out.name)
        return target


# --- 도우미 ---------------------------------------------------------------

def _collect_outputs(results: Iterable) -> list[OutputFile]:
    files: list[OutputFile] = []
    seen: set[Path] = set()
    for result in results:
        for path in result.outputs:
            path = Path(path)
            if path in seen or not path.exists():
                continue
            seen.add(path)
            files.append(OutputFile(name=path.name, path=path, size=path.stat().st_size))
    return files


def _average_confidence(results: Iterable) -> float:
    scored = [r.confidence for r in results if r.confidence >= 0]
    return sum(scored) / len(scored) if scored else -1.0


def _preview_text(results: Iterable) -> str:
    chunks: list[str] = []
    total = 0
    for result in results:
        text = result.document.text.strip()
        if not text:
            continue
        chunks.append(text)
        total += len(text)
        if total >= PREVIEW_LIMIT:
            break
    joined = "\n\n".join(chunks)
    return joined[:PREVIEW_LIMIT] + ("…" if len(joined) > PREVIEW_LIMIT else "")


def _unique_in(directory: Path, filename: str) -> Path:
    """폴더 안에서 겹치지 않는 이름을 고른다."""
    target = directory / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # 청소 실패가 서버를 멈추게 하지 않는다
        log.debug("작업 폴더 삭제 실패: %s", path, exc_info=True)


__all__ = ["Job", "JobState", "JobStore", "OutputFile", "STATE_LABELS"]

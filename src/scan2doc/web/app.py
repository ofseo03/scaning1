"""scan2doc 웹 서버 (FastAPI).

브라우저에서 사진·PDF를 올리면 서버가 OCR로 읽어 Word·한글 문서로 바꿔 주고,
결과를 내려받게 한다. 같은 API를 모바일 앱이나 다른 프로그램에서 그대로 써도 된다.

    scan2doc serve                 # http://127.0.0.1:8000

API 요약

    GET    /                       화면(정적 페이지)
    GET    /api/config             고를 수 있는 형식·언어·한도
    GET    /api/health             살아 있는지 확인
    GET    /api/doctor             OCR 엔진 설치 상태
    POST   /api/jobs               파일 올리고 변환 시작 → 작업 번호
    GET    /api/jobs/{id}          진행 상황과 결과 목록
    GET    /api/jobs/{id}/files/{n}  결과 파일 하나 내려받기
    GET    /api/jobs/{id}/archive  결과 전체를 ZIP으로
    GET    /api/jobs/{id}/text     인식된 글자만 텍스트로
    DELETE /api/jobs/{id}          작업과 파일 지우기
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import SUPPORTED_SUFFIXES
from ..errors import DependencyError, Scan2DocError
from ..ocr import available_engines
from ..writers import describe_writers
from .jobs import DEFAULT_TTL, DEFAULT_WORKERS, Job, JobState, JobStore
from .options import WEB_FORMATS, check_supported, parse_options

try:
    # 라우트의 형 표기(list[UploadFile])는 FastAPI가 실행 중에 이 모듈에서 찾는다.
    # 그래서 이 이름만은 모듈 수준에 있어야 한다. 없으면 create_app()이 안내한다.
    from fastapi import UploadFile
except ImportError:  # pragma: no cover - 선택 의존성
    UploadFile = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

FASTAPI_HINT = (
    "웹 서버를 쓰려면 추가 패키지가 필요합니다.\n"
    '  pip install "scan2doc[web]"\n'
    "  (또는 pip install fastapi uvicorn python-multipart)"
)

#: 언어 고르기 목록 — 자주 쓰는 것만 앞에 두고, 나머지는 직접 입력할 수 있다.
LANGUAGE_CHOICES = [
    {"code": "kor+eng", "label": "한국어 + 영어"},
    {"code": "kor", "label": "한국어만"},
    {"code": "eng", "label": "영어만"},
    {"code": "kor+eng+jpn", "label": "한국어 + 영어 + 일본어"},
    {"code": "kor+eng+chi_sim", "label": "한국어 + 영어 + 중국어(간체)"},
]


@dataclass
class WebSettings:
    """서버 동작을 정하는 값들. 환경 변수로도 바꿀 수 있다."""

    max_upload_mb: int = 50
    """파일 하나의 최대 크기(MB)."""

    max_files: int = 30
    """한 번에 올릴 수 있는 파일 개수."""

    workers: int = DEFAULT_WORKERS
    ttl: float = DEFAULT_TTL
    """변환이 끝난 뒤 결과를 남겨 두는 시간(초)."""

    workspace: Path | None = None
    """작업 폴더를 둘 위치. 비우면 임시 폴더를 만들어 쓴다."""

    cors_origins: list[str] = field(default_factory=list)
    """다른 주소의 앱에서 이 API를 부르게 하려면 여기에 적는다."""

    sweep_interval: float = 300.0

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * (1 << 20)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "WebSettings":
        """SCAN2DOC_WEB_* 환경 변수를 읽어 설정을 만든다."""
        env = os.environ if env is None else env
        settings = cls()
        settings.max_upload_mb = _env_int(env, "SCAN2DOC_WEB_MAX_UPLOAD_MB", settings.max_upload_mb)
        settings.max_files = _env_int(env, "SCAN2DOC_WEB_MAX_FILES", settings.max_files)
        settings.workers = _env_int(env, "SCAN2DOC_WEB_WORKERS", settings.workers)
        settings.ttl = _env_int(env, "SCAN2DOC_WEB_TTL", int(settings.ttl))
        workspace = env.get("SCAN2DOC_WEB_WORKSPACE", "").strip()
        if workspace:
            settings.workspace = Path(workspace)
        origins = env.get("SCAN2DOC_WEB_CORS", "").strip()
        if origins:
            settings.cors_origins = [o.strip() for o in origins.split(",") if o.strip()]
        return settings


def _env_int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("%s 값을 숫자로 읽을 수 없어 기본값(%s)을 씁니다: %r", key, default, raw)
        return default


def _import_fastapi():
    """FastAPI가 없으면 설치 방법을 알려 주는 오류를 낸다."""
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:
        raise DependencyError(FASTAPI_HINT) from exc
    return fastapi


def create_app(settings: WebSettings | None = None, *, store: JobStore | None = None):
    """FastAPI 애플리케이션을 만든다.

    테스트에서는 store를 직접 넣어 임시 폴더를 통제할 수 있다.
    """
    _import_fastapi()
    from fastapi import FastAPI, File, Form, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles

    settings = settings or WebSettings.from_env()
    store = store or JobStore(
        settings.workspace,
        max_workers=settings.workers,
        ttl=settings.ttl,
    )
    sweeper = _Sweeper(store, settings.sweep_interval)

    @asynccontextmanager
    async def lifespan(app):
        sweeper.start()          # 서버가 사는 동안 오래된 작업 폴더를 치운다
        yield
        sweeper.stop()
        store.shutdown()

    app = FastAPI(
        title="scan2doc",
        version=__version__,
        description="사진·PDF를 OCR로 읽어 Word(.docx)·한글(.hwpx) 문서로 바꿉니다.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store

    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )

    @app.exception_handler(Scan2DocError)
    def _handle_known(request: Request, exc: Scan2DocError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    # --- 정보 --------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/config")
    def config() -> dict:
        """화면을 그리는 데 필요한 선택지와 한도."""
        return {
            "version": __version__,
            # WEB_FORMATS 순서(자주 쓰는 것부터)를 그대로 화면에 보여 준다.
            "formats": sorted(
                (
                    {"name": name, "extension": ext, "description": desc}
                    for name, ext, desc in describe_writers()
                    if name in WEB_FORMATS
                ),
                key=lambda f: WEB_FORMATS.index(f["name"]),
            ),
            "default_formats": ["docx", "hwpx"],
            "languages": LANGUAGE_CHOICES,
            "engines": available_engines(),
            "accept": sorted(SUPPORTED_SUFFIXES),
            "limits": {
                "max_upload_mb": settings.max_upload_mb,
                "max_files": settings.max_files,
                "ttl_seconds": int(settings.ttl),
            },
        }

    @app.get("/api/doctor")
    def doctor() -> dict:
        """OCR 엔진과 파이썬 패키지가 준비됐는지 점검한다."""
        from ..doctor import run_doctor

        result = run_doctor()
        return {"ok": result.ok, "report": "\n".join(result.lines)}

    # --- 작업 --------------------------------------------------------------

    def _get_job(job_id: str) -> Job:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="그런 작업이 없습니다(이미 지워졌을 수 있습니다).")
        return job

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        files: list[UploadFile] = File(..., description="이미지 또는 PDF"),
        options: str = Form("{}", description="변환 설정(JSON)"),
    ) -> dict:
        """파일을 받아 변환을 시작하고 작업 번호를 돌려준다."""
        if not files:
            raise Scan2DocError("변환할 파일을 올려 주세요.")
        if len(files) > settings.max_files:
            raise Scan2DocError(
                f"한 번에 {settings.max_files}개까지 올릴 수 있습니다(받은 개수: {len(files)})."
            )

        convert_options = parse_options(_load_json(options))
        job = store.create(convert_options)
        try:
            for upload in files:
                name = check_supported(upload.filename or "upload")
                store.add_upload(job, name, upload.file,
                                 max_bytes=settings.max_upload_bytes)
        except Scan2DocError:
            store.delete(job.id)
            raise

        store.start(job)
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        return _get_job(job_id).to_dict()

    @app.get("/api/jobs/{job_id}/files/{index}")
    def job_file(job_id: str, index: int):
        job = _get_job(job_id)
        if not 0 <= index < len(job.outputs):
            raise HTTPException(status_code=404, detail="그런 결과 파일이 없습니다.")
        output = job.outputs[index]
        if not output.path.exists():
            raise HTTPException(status_code=410, detail="결과 파일이 이미 지워졌습니다.")
        return FileResponse(output.path, filename=output.name,
                            media_type="application/octet-stream")

    @app.get("/api/jobs/{job_id}/archive")
    def job_archive(job_id: str):
        job = _get_job(job_id)
        if job.state is not JobState.DONE:
            raise HTTPException(status_code=409, detail="아직 변환이 끝나지 않았습니다.")
        archive = store.archive_path(job)
        return FileResponse(archive, filename=archive.name, media_type="application/zip")

    @app.get("/api/jobs/{job_id}/text", response_class=PlainTextResponse)
    def job_text(job_id: str) -> str:
        job = _get_job(job_id)
        if job.state is not JobState.DONE:
            raise HTTPException(status_code=409, detail="아직 변환이 끝나지 않았습니다.")
        return job.preview

    @app.delete("/api/jobs/{job_id}")
    def job_delete(job_id: str) -> dict:
        if not store.delete(job_id):
            raise HTTPException(status_code=404, detail="그런 작업이 없습니다.")
        return {"deleted": job_id}

    # --- 화면 --------------------------------------------------------------

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def index() -> str:
            return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

        # PWA 파일은 루트에서 받아야 앱 전체가 설치 범위에 들어온다.
        @app.get("/manifest.webmanifest", include_in_schema=False)
        def manifest():
            return FileResponse(STATIC_DIR / "manifest.webmanifest",
                                media_type="application/manifest+json")

        @app.get("/sw.js", include_in_schema=False)
        def service_worker():
            return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript")

    return app


def _load_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Scan2DocError(f"설정(JSON)을 읽을 수 없습니다: {exc.msg}") from None
    if not isinstance(data, dict):
        raise Scan2DocError("설정은 JSON 객체여야 합니다.")
    return data


class _Sweeper:
    """다 끝나고 시간이 지난 작업 폴더를 주기적으로 치우는 스레드."""

    def __init__(self, store: JobStore, interval: float) -> None:
        self._store = store
        self._interval = max(10.0, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="scan2doc-sweeper",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                removed = self._store.sweep()
                if removed:
                    log.info("오래된 작업 %d개를 정리했습니다.", removed)
            except Exception:  # 청소 실패가 서버를 멈추게 하지 않는다
                log.debug("작업 정리 실패", exc_info=True)


__all__ = ["WebSettings", "create_app"]

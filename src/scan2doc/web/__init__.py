"""웹사이트와 어플리케이션을 위한 HTTP 계층.

CLI·GUI와 같은 파이프라인을 쓰되, 입출력만 HTTP로 바꾼 것이다.

    from scan2doc.web import create_app
    app = create_app()          # uvicorn scan2doc.web:app_factory --factory

FastAPI·uvicorn은 여기서만 쓰므로 `pip install "scan2doc[web]"` 로 따로 받는다.
없는 채로 부르면 설치 방법을 알려 주는 DependencyError가 난다.
"""

from __future__ import annotations

from .app import WebSettings, create_app
from .jobs import Job, JobState, JobStore
from .server import DEFAULT_HOST, DEFAULT_PORT, app_factory, serve

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "Job",
    "JobState",
    "JobStore",
    "WebSettings",
    "app_factory",
    "create_app",
    "serve",
]

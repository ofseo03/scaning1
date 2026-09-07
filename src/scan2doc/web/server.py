"""웹 서버 실행 (scan2doc serve)."""

from __future__ import annotations

import logging
import socket
import threading
import webbrowser

from ..errors import DependencyError
from .app import FASTAPI_HINT, WebSettings, create_app

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

UVICORN_HINT = (
    "웹 서버를 띄우려면 uvicorn이 필요합니다.\n"
    '  pip install "scan2doc[web]"'
)


def app_factory():
    """uvicorn --reload 처럼 앱을 다시 만들어야 할 때 쓰는 진입점."""
    return create_app()


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    settings: WebSettings | None = None,
    reload: bool = False,
    open_browser: bool = False,
    log_level: str = "info",
) -> int:
    """웹 서버를 띄운다. 서버가 멈출 때까지 돌아온다."""
    try:
        import uvicorn
    except ImportError as exc:
        raise DependencyError(UVICORN_HINT) from exc

    url = f"http://{_display_host(host)}:{port}"
    print(f"scan2doc 웹 서버: {url}")
    print(f"  · API 문서: {url}/api/docs")
    print("  · 멈추려면 Ctrl+C")

    if open_browser:
        _open_later(url)

    try:
        if reload:
            # 코드가 바뀔 때마다 새 프로세스에서 앱을 다시 만들어야 한다.
            uvicorn.run("scan2doc.web.server:app_factory", factory=True,
                        host=host, port=port, reload=True, log_level=log_level)
        else:
            uvicorn.run(create_app(settings), host=host, port=port, log_level=log_level)
    except KeyboardInterrupt:  # pragma: no cover - 사용자가 멈춘 경우
        print("\n서버를 멈췄습니다.")
    except OSError as exc:
        if getattr(exc, "errno", None) in (48, 98):  # 주소가 이미 쓰이는 중
            print(f"오류: {port}번 포트를 이미 쓰고 있습니다. --port 로 다른 번호를 주세요.")
            return 1
        raise
    return 0


def _display_host(host: str) -> str:
    """0.0.0.0 처럼 그대로는 눌러 볼 수 없는 주소를 보기 좋게 바꾼다."""
    if host in ("0.0.0.0", "::", ""):
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "localhost"
    return host


def _open_later(url: str, delay: float = 1.0) -> None:
    """서버가 뜰 시간을 조금 준 뒤 브라우저를 연다."""
    threading.Timer(delay, lambda: webbrowser.open(url)).start()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - 얇은 진입점
    import argparse

    parser = argparse.ArgumentParser(prog="scan2doc serve", description="scan2doc 웹 서버")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--open", dest="open_browser", action="store_true")
    args = parser.parse_args(argv)
    return serve(args.host, args.port, reload=args.reload, open_browser=args.open_browser)


__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "FASTAPI_HINT", "app_factory", "serve"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""웹사이트·어플리케이션 계층(scan2doc.web).

실제 OCR은 돌리지 않는다. 파이프라인은 가짜로 바꿔 두고, 웹이 맡은 일
— 설정 해석, 파일 안전 처리, 작업 관리, HTTP 규약 — 만 확인한다.
"""

from __future__ import annotations

import importlib.util
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scan2doc.errors import InputError, Scan2DocError
from scan2doc.web.jobs import JobState, JobStore
from scan2doc.web.options import check_supported, parse_options, safe_filename

#: 웹 서버는 선택 의존성이다. 없으면 API 테스트만 건너뛰고 나머지는 그대로 돌린다.
WEB_DEPS = ("fastapi", "multipart")
requires_web = pytest.mark.skipif(
    any(importlib.util.find_spec(name) is None for name in WEB_DEPS),
    reason='웹 API 테스트에는 pip install "scan2doc[web]" 이 필요합니다',
)


# --- 가짜 파이프라인 ------------------------------------------------------

def fake_convert_factory(*, confidence: float = 92.0, text: str = "가나다 ABC"):
    """options.output 폴더에 결과 파일을 만들어 놓는 가짜 convert()."""

    def fake_convert(inputs, options, progress=None):
        if progress is not None:
            progress("page", "1쪽 처리 중", 0.5)
        outputs = []
        base = Path(options.output)
        for source in inputs:
            for fmt in options.formats:
                target = base / f"{Path(source).stem}.{fmt}"
                target.write_text(f"{fmt}: {text}", encoding="utf-8")
                outputs.append(target)
        return [SimpleNamespace(
            outputs=outputs,
            page_count=len(list(inputs)),
            elapsed=0.01,
            text_layer_pages=0,
            confidence=confidence,
            document=SimpleNamespace(text=text),
        )]

    return fake_convert


@pytest.fixture
def patched_convert(monkeypatch):
    """scan2doc.pipeline.convert 를 가짜로 바꾼다(작업 스레드가 이 이름을 찾아 쓴다)."""
    import scan2doc.pipeline as pipeline

    fake = fake_convert_factory()
    monkeypatch.setattr(pipeline, "convert", fake)
    return fake


@pytest.fixture
def store(tmp_path):
    store = JobStore(tmp_path / "work", max_workers=1, ttl=60)
    yield store
    store.shutdown()


def wait_until_finished(store, job_id, timeout=10.0):
    """작업이 끝날 때까지 기다린다(작업자 스레드에서 돌기 때문)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = store.get(job_id)
        if job is None or job.finished:
            return job
        time.sleep(0.02)
    raise AssertionError("작업이 제한 시간 안에 끝나지 않았습니다.")


# --- 설정 해석 ------------------------------------------------------------

class TestParseOptions:
    def test_빈_설정이면_기본값을_쓴다(self):
        options = parse_options({})
        assert options.formats == ["docx", "hwpx"]
        assert options.language == "kor+eng"
        assert options.psm == "auto"

    def test_결과는_작업_폴더에만_쓰므로_덮어쓰기가_켜진다(self):
        assert parse_options({}).overwrite is True

    def test_형식을_목록으로도_문자열로도_받는다(self):
        assert parse_options({"formats": ["docx", "txt"]}).formats == ["docx", "txt"]
        assert parse_options({"formats": "docx, md"}).formats == ["docx", "md"]

    def test_같은_형식을_두_번_적어도_한_번만_남는다(self):
        assert parse_options({"formats": "docx,docx"}).formats == ["docx"]

    @pytest.mark.parametrize("bad", ["exe", "docx,bat", ""])
    def test_모르는_형식은_거절한다(self, bad):
        with pytest.raises(Scan2DocError):
            parse_options({"formats": bad if bad else []})

    def test_참거짓을_문자열로도_받는다(self):
        assert parse_options({"merge": "true"}).merge is True
        assert parse_options({"merge": "off"}).merge is False

    def test_이상한_참거짓은_거절한다(self):
        with pytest.raises(Scan2DocError):
            parse_options({"merge": "아마도"})

    @pytest.mark.parametrize("bad", ["kor; rm -rf /", "kor eng", "--tessdata-dir=/etc"])
    def test_언어_코드에_명령을_섞을_수_없다(self, bad):
        # 언어 값은 tesseract 명령줄로 넘어간다. 형식을 벗어나면 여기서 막는다.
        with pytest.raises(Scan2DocError):
            parse_options({"language": bad})

    def test_psm은_auto_또는_0에서_13(self):
        assert parse_options({"psm": "auto"}).psm == "auto"
        assert parse_options({"psm": "6"}).psm == 6
        with pytest.raises(Scan2DocError):
            parse_options({"psm": 99})

    def test_해상도는_범위를_벗어나면_거절한다(self):
        assert parse_options({"dpi": 400}).dpi == 400
        with pytest.raises(Scan2DocError):
            parse_options({"dpi": 5000})

    def test_쪽_범위는_숫자와_쉼표만_받는다(self):
        assert parse_options({"pages": "1-3,7"}).pages == "1-3,7"
        with pytest.raises(Scan2DocError):
            parse_options({"pages": "1-3; ls"})

    def test_사진_보정_설정이_전해진다(self):
        options = parse_options({"preprocess": {"binarize": True, "deskew": False}})
        assert options.preprocess.binarize is True
        assert options.preprocess.deskew is False
        assert options.preprocess.enabled is True

    def test_영문_글꼴을_비우면_한글_글꼴을_따라간다(self):
        options = parse_options({"font_korean": "함초롬바탕"})
        assert options.font_latin == "함초롬바탕"

    def test_서버_경로를_정하는_값은_받지_않는다(self):
        options = parse_options({
            "output": "/etc",
            "report": "/etc/passwd",
            "tesseract_cmd": "/bin/sh",
            "recursive": True,
        })
        assert options.output is None
        assert options.report is None
        assert options.tesseract_cmd is None
        assert options.recursive is False


# --- 파일 이름 안전 처리 ---------------------------------------------------

class TestSafeFilename:
    @pytest.mark.parametrize("given", [
        "../../etc/passwd.png",
        "/etc/passwd.png",
        r"C:\Windows\system32\passwd.png",
        "..\\..\\passwd.png",
    ])
    def test_경로를_떼어내고_이름만_남긴다(self, given):
        name = safe_filename(given)
        assert name == "passwd.png"
        assert "/" not in name and "\\" not in name

    def test_한글_이름은_그대로_둔다(self):
        assert safe_filename("계약서 (사본).jpg") == "계약서 (사본).jpg"

    def test_이름이_비면_대체_이름을_준다(self):
        assert safe_filename("   ") == "upload"

    def test_지원하는_확장자만_통과시킨다(self):
        assert check_supported("사진.JPG") == "사진.JPG"
        with pytest.raises(InputError):
            check_supported("악성.exe")


# --- 작업 관리 -------------------------------------------------------------

class TestJobStore:
    def test_작업을_만들면_폴더가_생기고_결과_경로가_고정된다(self, store):
        job = store.create(parse_options({}))
        assert job.upload_dir.is_dir()
        assert job.output_dir.is_dir()
        assert job.options.output == job.output_dir

    def test_올린_파일을_작업_폴더에_저장한다(self, store):
        job = store.create(parse_options({}))
        path = store.add_upload(job, "a.png", io.BytesIO(b"1234"))
        assert path.read_bytes() == b"1234"
        assert job.sources == ["a.png"]

    def test_이름이_겹치면_번호를_붙인다(self, store):
        job = store.create(parse_options({}))
        store.add_upload(job, "a.png", io.BytesIO(b"1"))
        second = store.add_upload(job, "a.png", io.BytesIO(b"2"))
        assert second.name == "a (1).png"

    def test_너무_큰_파일은_거절하고_흔적을_남기지_않는다(self, store):
        job = store.create(parse_options({}))
        with pytest.raises(Scan2DocError):
            store.add_upload(job, "big.png", io.BytesIO(b"x" * 100), max_bytes=10)
        assert list(job.upload_dir.iterdir()) == []

    def test_빈_파일도_거절한다(self, store):
        job = store.create(parse_options({}))
        with pytest.raises(Scan2DocError):
            store.add_upload(job, "empty.png", io.BytesIO(b""))

    def test_파일이_없으면_시작할_수_없다(self, store):
        job = store.create(parse_options({}))
        with pytest.raises(Scan2DocError):
            store.start(job)

    def test_변환이_끝나면_결과와_요약이_담긴다(self, store, patched_convert):
        job = store.create(parse_options({"formats": ["docx", "txt"]}))
        store.add_upload(job, "계약서.png", io.BytesIO(b"image"))
        store.start(job)

        finished = wait_until_finished(store, job.id)
        assert finished.state is JobState.DONE
        assert finished.progress == 1.0
        assert sorted(o.name for o in finished.outputs) == ["계약서.docx", "계약서.txt"]
        assert all(o.size > 0 for o in finished.outputs)
        assert finished.confidence == pytest.approx(92.0)
        assert "가나다" in finished.preview

    def test_변환이_실패해도_작업_하나만_실패한다(self, store, monkeypatch):
        import scan2doc.pipeline as pipeline

        def boom(inputs, options, progress=None):
            raise Scan2DocError("읽을 수 있는 쪽이 없습니다")

        monkeypatch.setattr(pipeline, "convert", boom)
        job = store.create(parse_options({}))
        store.add_upload(job, "a.png", io.BytesIO(b"x"))
        store.start(job)

        finished = wait_until_finished(store, job.id)
        assert finished.state is JobState.FAILED
        assert "읽을 수 있는 쪽이 없습니다" in finished.error

    def test_예상_못한_오류도_붙잡아_실패로_남긴다(self, store, monkeypatch):
        import scan2doc.pipeline as pipeline

        def boom(inputs, options, progress=None):
            raise RuntimeError("어딘가 깨졌다")

        monkeypatch.setattr(pipeline, "convert", boom)
        job = store.create(parse_options({}))
        store.add_upload(job, "a.png", io.BytesIO(b"x"))
        store.start(job)

        finished = wait_until_finished(store, job.id)
        assert finished.state is JobState.FAILED
        assert "어딘가 깨졌다" in finished.error

    def test_결과를_ZIP으로_묶는다(self, store, patched_convert):
        import zipfile

        job = store.create(parse_options({"formats": ["docx", "txt"]}))
        store.add_upload(job, "a.png", io.BytesIO(b"x"))
        store.start(job)
        wait_until_finished(store, job.id)

        archive = store.archive_path(job)
        with zipfile.ZipFile(archive) as zf:
            assert sorted(zf.namelist()) == ["a.docx", "a.txt"]

    def test_작업을_지우면_폴더까지_사라진다(self, store, patched_convert):
        job = store.create(parse_options({}))
        store.add_upload(job, "a.png", io.BytesIO(b"x"))
        root = job.root
        assert store.delete(job.id) is True
        assert not root.exists()
        assert store.get(job.id) is None

    def test_시간이_지난_작업만_청소한다(self, store, patched_convert):
        old = store.create(parse_options({}))
        store.add_upload(old, "a.png", io.BytesIO(b"x"))
        store.start(old)
        wait_until_finished(store, old.id)
        old.finished_at = time.time() - store.ttl - 10

        fresh = store.create(parse_options({}))
        store.add_upload(fresh, "b.png", io.BytesIO(b"x"))
        store.start(fresh)
        wait_until_finished(store, fresh.id)

        assert store.sweep() == 1
        assert store.get(old.id) is None
        assert store.get(fresh.id) is not None


# --- HTTP API --------------------------------------------------------------

@pytest.fixture
def client(tmp_path, patched_convert):
    from fastapi.testclient import TestClient

    from scan2doc.web.app import WebSettings, create_app

    settings = WebSettings(max_upload_mb=1, max_files=3, workers=1, ttl=60)
    store = JobStore(tmp_path / "api", max_workers=1, ttl=60)
    with TestClient(create_app(settings, store=store)) as client:
        yield client


def upload(client, files, options=None):
    payload = [("files", (name, io.BytesIO(data), "image/png")) for name, data in files]
    return client.post("/api/jobs", files=payload,
                       data={"options": json.dumps(options or {})})


def run_to_completion(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("작업이 제한 시간 안에 끝나지 않았습니다.")


@requires_web
class TestApi:
    def test_상태_확인(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_설정에_형식과_한도가_들어_있다(self, client):
        config = client.get("/api/config").json()
        names = [f["name"] for f in config["formats"]]
        assert "docx" in names and "hwpx" in names
        assert config["limits"]["max_files"] == 3
        assert ".pdf" in config["accept"]

    def test_화면을_돌려준다(self, client):
        page = client.get("/")
        assert page.status_code == 200
        assert "scan2doc" in page.text

    def test_앱_설치_정보를_루트에서_받는다(self, client):
        manifest = client.get("/manifest.webmanifest")
        assert manifest.status_code == 200
        assert manifest.json()["start_url"] == "/"
        assert client.get("/sw.js").status_code == 200

    def test_올리고_기다리면_내려받을_수_있다(self, client):
        response = upload(client, [("계약서.png", b"image-bytes")],
                          {"formats": ["docx", "txt"]})
        assert response.status_code == 202
        job_id = response.json()["id"]

        job = run_to_completion(client, job_id)
        assert job["state"] == "done"
        assert len(job["outputs"]) == 2
        assert job["archive_url"] == f"/api/jobs/{job_id}/archive"

        first = client.get(job["outputs"][0]["url"])
        assert first.status_code == 200
        assert first.content

        archive = client.get(job["archive_url"])
        assert archive.status_code == 200
        assert archive.headers["content-type"] == "application/zip"

        text = client.get(f"/api/jobs/{job_id}/text")
        assert "가나다" in text.text

    def test_설정을_주지_않아도_돌아간다(self, client):
        job_id = upload(client, [("a.png", b"x")]).json()["id"]
        assert run_to_completion(client, job_id)["state"] == "done"

    def test_지원하지_않는_형식은_거절한다(self, client):
        response = upload(client, [("악성.exe", b"MZ")])
        assert response.status_code == 400
        assert "지원하지 않는" in response.json()["error"]

    def test_설정이_잘못되면_거절한다(self, client):
        response = upload(client, [("a.png", b"x")], {"formats": ["exe"]})
        assert response.status_code == 400

    def test_설정_JSON이_깨졌으면_알려_준다(self, client):
        response = client.post("/api/jobs",
                               files=[("files", ("a.png", io.BytesIO(b"x"), "image/png"))],
                               data={"options": "{이건 JSON이 아니다"})
        assert response.status_code == 400
        assert "JSON" in response.json()["error"]

    def test_한_번에_올릴_수_있는_개수를_넘으면_거절한다(self, client):
        response = upload(client, [(f"{i}.png", b"x") for i in range(4)])
        assert response.status_code == 400
        assert "3개까지" in response.json()["error"]

    def test_크기_한도를_넘으면_거절한다(self, client):
        response = upload(client, [("big.png", b"x" * (2 << 20))])
        assert response.status_code == 400
        assert "너무 큽니다" in response.json()["error"]

    def test_없는_작업은_404(self, client):
        assert client.get("/api/jobs/없는번호").status_code == 404
        assert client.delete("/api/jobs/없는번호").status_code == 404

    def test_끝나지_않은_작업의_결과는_409(self, client, monkeypatch):
        import scan2doc.pipeline as pipeline

        def slow(inputs, options, progress=None):
            time.sleep(1.0)
            return []

        monkeypatch.setattr(pipeline, "convert", slow)
        job_id = upload(client, [("a.png", b"x")]).json()["id"]
        assert client.get(f"/api/jobs/{job_id}/archive").status_code == 409
        assert client.get(f"/api/jobs/{job_id}/text").status_code == 409

    def test_없는_결과_번호는_404(self, client):
        job_id = upload(client, [("a.png", b"x")], {"formats": ["txt"]}).json()["id"]
        run_to_completion(client, job_id)
        assert client.get(f"/api/jobs/{job_id}/files/9").status_code == 404

    def test_작업을_지울_수_있다(self, client):
        job_id = upload(client, [("a.png", b"x")]).json()["id"]
        run_to_completion(client, job_id)
        assert client.delete(f"/api/jobs/{job_id}").status_code == 200
        assert client.get(f"/api/jobs/{job_id}").status_code == 404

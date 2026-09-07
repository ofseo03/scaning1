# 웹사이트·어플리케이션

`scan2doc serve` 는 **CLI와 똑같은 파이프라인**을 HTTP로 감싼 것입니다.
Tesseract와 글꼴을 컴퓨터마다 깔 필요 없이 서버 한 대만 갖춰 두면,
브라우저·휴대폰·다른 프로그램이 모두 같은 변환을 쓸 수 있습니다.

```
브라우저 / 휴대폰 / 다른 프로그램
        │  multipart 업로드
        ▼
   FastAPI (web/app.py)  ──▶  작업 관리 (web/jobs.py)  ──▶  파이프라인 (pipeline.py)
        ▲                          │ 작업자 스레드            OCR → 구조 복원 → 문서
        └── 진행 상황·결과 내려받기 ┘
```

OCR은 한 쪽에 몇 초씩 걸립니다. 그래서 요청을 붙잡아 두지 않고 **작업 번호를 먼저
돌려준 뒤**, 클라이언트가 그 번호로 진행 상황을 물어보는 방식입니다.

## 설치와 실행

```bash
pip install -e ".[web]"        # fastapi · uvicorn · python-multipart
scan2doc serve                 # http://127.0.0.1:8000
scan2doc serve --open          # 브라우저까지 열기
scan2doc serve --host 0.0.0.0  # 같은 공유기의 휴대폰에서도 접속
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--host` | `127.0.0.1` | 들을 주소 |
| `--port` | `8000` | 포트 |
| `--workers` | `2` | 동시에 처리할 변환 개수 |
| `--max-upload-mb` | `50` | 파일 하나의 최대 크기 |
| `--workspace` | 임시 폴더 | 올린 파일과 결과를 둘 곳 |
| `--open` / `--reload` | 꺼짐 | 브라우저 열기 / 코드 변경 시 재시작 |

환경 변수로도 같은 값을 줄 수 있습니다(컨테이너에서 쓰기 좋습니다).

| 변수 | 뜻 |
|---|---|
| `SCAN2DOC_WEB_MAX_UPLOAD_MB` | 파일 하나의 최대 크기(MB) |
| `SCAN2DOC_WEB_MAX_FILES` | 한 번에 올릴 수 있는 개수 |
| `SCAN2DOC_WEB_WORKERS` | 동시 변환 개수 |
| `SCAN2DOC_WEB_TTL` | 결과를 남겨 두는 시간(초) |
| `SCAN2DOC_WEB_WORKSPACE` | 작업 폴더 위치 |
| `SCAN2DOC_WEB_CORS` | 허용할 다른 출처(쉼표로 구분) |

## API

### `POST /api/jobs` — 올리고 변환 시작

`multipart/form-data` 로 보냅니다.

| 필드 | 설명 |
|---|---|
| `files` | 이미지 또는 PDF (여러 개 가능) |
| `options` | 변환 설정 JSON 문자열 (생략 가능) |

```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
     -F "files=@계약서.jpg" -F "files=@부속서류.pdf" \
     -F 'options={"formats":["docx","hwpx"],"merge":true,"title":"2026년 계약서"}'
```

`202 Accepted` 와 함께 작업 정보를 돌려줍니다.

```json
{ "id": "3f9c1a…", "state": "queued", "progress": 0.0, "sources": ["계약서.jpg"] }
```

**`options` 에 넣을 수 있는 값** (모두 생략 가능, 괄호 안은 기본값)

| 키 | 값 |
|---|---|
| `formats` | `docx` `hwpx` `hwpml` `txt` `md` 중 목록 (`["docx","hwpx"]`) |
| `hwp_format` | `hwpx` \| `hwpml` (`hwpx`) |
| `merge` | 여러 입력을 문서 하나로 (`false`) |
| `title` | 문서 맨 앞 제목 (`""`) |
| `language` | Tesseract 언어 코드 (`kor+eng`) |
| `psm` | `auto` 또는 0~13 (`auto`) |
| `oem` / `ocr_timeout` / `min_confidence` | 엔진 모드 · 쪽당 제한 시간(초) · 최소 신뢰도 |
| `dpi` | PDF 렌더링 해상도, 72~600 (`300`) |
| `pages` | 쪽 범위 `"1-3,7"` (전체) |
| `pdf_text` | `auto` \| `always` \| `never` (`auto`) |
| `detect_headings` / `detect_lists` / `keep_line_breaks` / `page_break` / `embed_image` | 문서 구성 |
| `font_korean` / `font_latin` / `font_size` / `line_spacing` | 서식 |
| `preprocess` | `{"enabled":true,"deskew":true,"auto_rotate":true,"binarize":false,"denoise":false}` |

CLI 옵션과 이름이 같습니다. 다만 **서버의 파일 시스템을 가리키는 값
(`output`, `report`, `tesseract_cmd`, `recursive`)은 받지 않습니다.**
결과는 언제나 그 작업의 폴더 안에만 씁니다.

### `GET /api/jobs/{id}` — 진행 상황

```json
{
  "id": "3f9c1a…",
  "state": "running",          // queued → running → done | failed
  "state_label": "변환 중",
  "message": "계약서.jpg · 1쪽 처리 중",
  "progress": 0.5,             // 0.0 ~ 1.0
  "outputs": [],
  "confidence": -1.0
}
```

끝나면(`state: "done"`) 결과가 채워집니다.

```json
{
  "state": "done",
  "page_count": 3,
  "confidence": 91.4,
  "elapsed": 6.7,
  "outputs": [
    { "index": 0, "name": "계약서.docx", "size": 38104, "url": "/api/jobs/3f9c1a…/files/0" },
    { "index": 1, "name": "계약서.hwpx", "size": 12044, "url": "/api/jobs/3f9c1a…/files/1" }
  ],
  "archive_url": "/api/jobs/3f9c1a…/archive",
  "preview": "제1장 총칙\n\n제1조 (목적) …"
}
```

실패하면 `state: "failed"` 와 `error` 에 사람이 읽을 이유가 담깁니다
(예: Tesseract가 없으면 설치 방법까지).

### 나머지

| 엔드포인트 | 하는 일 |
|---|---|
| `GET /api/jobs/{id}/files/{n}` | 결과 파일 하나 내려받기 |
| `GET /api/jobs/{id}/archive` | 결과 전체를 ZIP으로 (끝나기 전이면 409) |
| `GET /api/jobs/{id}/text` | 인식된 글자만 텍스트로 |
| `DELETE /api/jobs/{id}` | 작업과 파일을 즉시 지우기 |
| `GET /api/config` | 고를 수 있는 형식·언어와 업로드 한도 |
| `GET /api/doctor` | OCR 엔진·패키지 설치 상태 (`scan2doc doctor` 와 같은 내용) |
| `GET /api/health` | 살아 있는지 확인 (헬스체크용) |
| `GET /api/docs` | 대화형 OpenAPI 문서 |

## 어플리케이션(PWA)으로 설치

웹 화면은 [PWA](https://web.dev/progressive-web-apps/)라서 앱처럼 설치됩니다.

- **아이폰·아이패드** — Safari에서 열고 공유 → *홈 화면에 추가*
- **안드로이드 크롬** — 메뉴 → *앱 설치*
- **데스크톱 크롬·엣지** — 주소창 오른쪽 설치 단추

설치하면 주소창 없이 열리고, 화면 껍데기는 캐시에서 바로 뜹니다.
**변환 API와 결과 파일은 캐시하지 않습니다** — 늘 서버의 최신 상태를 봅니다.

## 서버로 계속 띄워 두기

### systemd

```ini
# /etc/systemd/system/scan2doc.service
[Unit]
Description=scan2doc 웹 서버
After=network.target

[Service]
User=scan2doc
Environment=SCAN2DOC_WEB_WORKSPACE=/var/lib/scan2doc
Environment=SCAN2DOC_WEB_WORKERS=4
ExecStart=/opt/scan2doc/venv/bin/scan2doc serve --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### nginx 뒤에 두기

업로드 크기 제한과 시간 제한을 함께 늘려 줘야 합니다. OCR은 오래 걸립니다.

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    client_max_body_size 60m;      # --max-upload-mb 보다 넉넉하게
    proxy_read_timeout 600s;       # 큰 PDF 변환을 기다릴 수 있게
}
```

### 컨테이너

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-kor fonts-nanum \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[web,preprocess]"
ENV SCAN2DOC_WEB_WORKSPACE=/tmp/scan2doc
EXPOSE 8000
CMD ["scan2doc", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

한국어를 읽으려면 **`tesseract-ocr-kor` 언어 데이터**가 반드시 있어야 합니다.
컨테이너를 띄운 뒤 `/api/doctor` 로 확인하세요.

## 보안과 한계

이 서버는 **믿을 수 있는 망(집·사내망)에서 쓰는 것을 기본**으로 만들었습니다.
인터넷에 그대로 열어 둘 생각이라면 아래를 먼저 확인하세요.

- **로그인이 없습니다.** 작업 번호(무작위 16자리)를 아는 사람은 그 결과를 받을 수 있습니다.
  공개 서버라면 리버스 프록시에서 인증을 걸어 주세요.
- **기본은 이 컴퓨터에서만** 들립니다(`127.0.0.1`). `--host 0.0.0.0` 은 필요할 때만 쓰세요.
- **올린 파일과 결과는 `SCAN2DOC_WEB_TTL`(기본 1시간) 뒤 자동으로 지워집니다.**
  더 빨리 지우려면 `DELETE /api/jobs/{id}` 를 부르면 됩니다.
- 받아들이는 값은 허용 목록으로 검사합니다. 파일 이름은 경로를 떼어 내고,
  지원하지 않는 확장자와 크기를 넘는 파일은 거절합니다.
- 변환은 CPU를 많이 씁니다. `--workers` 를 코어 수보다 크게 잡지 마세요.

## 문제가 생기면

| 증상 | 볼 곳 |
|---|---|
| 변환이 곧바로 실패한다 | `/api/doctor` — Tesseract·한국어 데이터가 있는지 |
| 한국어가 깨져 나온다 | `tesseract-ocr-kor` 설치 여부, `language` 값 |
| 업로드가 413으로 막힌다 | 리버스 프록시의 `client_max_body_size` |
| 큰 PDF에서 504가 난다 | 프록시의 `proxy_read_timeout`, `ocr_timeout` |
| 인식률이 낮다 | 화면의 **흑백 이진화**, `dpi` 를 400으로, 더 밝게 재촬영 |

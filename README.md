# scan2doc

사진·스크린샷·PDF를 **OCR로 읽어 Word(.docx)와 한글(.hwpx) 문서로 바꿔 주는 프로그램**입니다.
글자만 뽑아내는 데서 그치지 않고 제목·문단·목록 구조까지 되살려서, 받아 적을 필요 없이
바로 고쳐 쓸 수 있는 문서를 만듭니다.

```
scan2doc 계약서.jpg
  → 계약서.docx, 계약서.hwpx
```

## 무엇을 할 수 있나요

| | |
|---|---|
| **입력** | JPG, PNG, BMP, GIF, TIFF(여러 장), WEBP, PDF, 폴더 통째로 |
| **출력** | Word `.docx`, 한글 `.hwpx` / `.hwpml`, 텍스트 `.txt`, 마크다운 `.md` |
| **언어** | 한국어 + 영어 기본, 그 밖에 Tesseract가 지원하는 모든 언어 |
| **구조 복원** | 제목 단계, 문단, 글머리표·번호 목록, 쪽 나눔 |
| **사진 보정** | 기울기 자동 교정, 90/180도 회전 감지, 흑백 이진화, 노이즈 제거 |
| **PDF** | 이미 글자가 들어 있는 PDF는 OCR 없이 그대로 뽑아내 더 정확하게 변환 |
| **사용법** | 명령줄(CLI), 창(GUI), **웹사이트·어플리케이션**, 파이썬 라이브러리 |

## 설치

### 1) Tesseract OCR 설치 (필수)

글자를 읽는 엔진입니다. 한국어를 쓰려면 한국어 데이터(`kor`)도 함께 설치해야 합니다.

```bash
# Ubuntu / Debian
sudo apt install tesseract-ocr tesseract-ocr-kor

# Fedora
sudo dnf install tesseract tesseract-langpack-kor

# macOS
brew install tesseract tesseract-lang
```

**Windows**는 [UB-Mannheim 설치본](https://github.com/UB-Mannheim/tesseract/wiki)을 받아
설치할 때 *Additional language data*에서 **Korean**을 체크하세요.
설치 경로를 PATH에 넣지 않았다면 실행할 때 알려 주면 됩니다:

```bash
scan2doc 사진.jpg --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

### 2) scan2doc 설치

```bash
git clone https://github.com/ofseo03/scaning1.git
cd scaning1
pip install -e .

# 사진 보정(기울기 교정·이진화)까지 쓰려면
pip install -e ".[preprocess]"
```

### 3) 제대로 깔렸는지 확인

```bash
scan2doc doctor
```

빠진 것이 있으면 무엇을 어떻게 설치하면 되는지 알려 줍니다.

## 빠른 시작

```bash
# 사진 한 장 → Word + 한글 문서
scan2doc 계약서.jpg

# 폴더 전체를 문서 하나로 합치기
scan2doc 스캔사진/ -o 결과/ --merge --title "2026년 계약서"

# PDF의 1~5쪽만 Word로
scan2doc 보고서.pdf -f docx --pages 1-5

# 스마트폰으로 찍어 그림자가 진 사진
scan2doc 영수증.jpg --binarize

# 영어 문서
scan2doc invoice.png -l eng

# 창(GUI)으로 쓰기
scan2doc gui

# 웹사이트로 쓰기 (브라우저·휴대폰)
scan2doc serve --open
```

출력 위치를 지정하지 않으면 원본 파일 옆에 같은 이름으로 저장합니다.
같은 이름이 이미 있으면 덮어쓰지 않고 `계약서 (1).docx`처럼 번호를 붙입니다
(`--overwrite`를 주면 덮어씁니다).

## 한글(HWP) 파일에 대해

기본 출력은 **`.hwpx`** 입니다. 한컴이 공개한 **OWPML(KS X 6101) 국가표준** 형식이라
문서화된 규격대로 만들 수 있고, **한/글 2014 이상에서 그냥 열립니다.**

- **`.hwp`로 바꾸고 싶다면** 한/글에서 `.hwpx`를 연 뒤 *다른 이름으로 저장 → 한글 문서(*.hwp)* 를
  고르면 됩니다. 옛 `.hwp`는 공개되지 않은 이진 형식이라 외부 프로그램이 직접 쓰기 어렵습니다.
- **한/글 2007~2010**처럼 `.hwpx`를 못 여는 버전이라면 `--hwp-format hwpml`을 쓰세요.
  단일 XML 형식(`.hwpml`)으로 저장합니다.

```bash
scan2doc 문서.jpg -f hwp                      # → 문서.hwpx
scan2doc 문서.jpg -f hwp --hwp-format hwpml   # → 문서.hwpml
```

## 인식률을 높이는 요령

변환이 끝나면 인식 신뢰도(%)를 함께 보여 줍니다. 70% 아래로 나온다면:

| 상황 | 해 볼 것 |
|---|---|
| 그림자·얼룩이 있는 사진 | `--binarize` |
| 지저분한 팩스·복사본 | `--denoise --binarize` |
| 글씨가 작거나 사진이 흐림 | 더 가까이·밝게 다시 촬영 (300dpi 이상 권장) |
| PDF가 흐릿하게 변환됨 | `--dpi 400` |
| 신문처럼 단이 여러 개 | `--psm 3` |
| 표지·간판처럼 글자가 흩어져 있음 | `--psm 11` |
| 표·영수증의 줄을 그대로 살리고 싶음 | `--keep-line-breaks` |
| 한국어만 있는 문서 | `-l kor` (영어를 빼면 오인식이 줄어듭니다) |

기본값인 `--psm auto`는 한 단 문서(모드 4)로 먼저 읽어 보고, 결과가 신통찮으면
전체 자동 분석(모드 3)으로 한 번 더 시도해 더 나은 쪽을 씁니다.

## 전체 옵션

```
scan2doc [convert] 입력... [옵션]
scan2doc doctor      환경 점검
scan2doc gui         창 띄우기
scan2doc serve       웹 서버 (브라우저·휴대폰에서 쓰기)
scan2doc formats     출력 형식 목록
```

**출력**

| 옵션 | 설명 |
|---|---|
| `-o, --output` | 저장할 파일 또는 폴더 |
| `-f, --format` | `docx,hwpx,hwpml,txt,md` 중 골라 쉼표로 나열 (기본 `docx,hwpx`) |
| `--hwp-format` | `hwpx`(기본) 또는 `hwpml` |
| `--merge` | 여러 입력을 문서 하나로 |
| `--overwrite` | 같은 이름 파일 덮어쓰기 |
| `--title` | 문서 맨 앞에 넣을 제목 |
| `--report` | 인식 결과를 JSON으로도 저장 |

**인식(OCR)**

| 옵션 | 설명 |
|---|---|
| `-l, --lang` | 인식 언어 (기본 `kor+eng`) |
| `--psm` | `auto`(기본) 또는 0~13 |
| `--oem` | Tesseract 엔진 모드 (기본 3) |
| `--tesseract-cmd` | tesseract 실행 파일 경로 |
| `--min-confidence` | 이 신뢰도 미만 낱말 버리기 |
| `--ocr-timeout` | 한 쪽당 제한 시간(초, 기본 180) |

**입력 처리**

| 옵션 | 설명 |
|---|---|
| `--dpi` | PDF 렌더링 해상도 (기본 300) |
| `--pages` | 쪽 범위 (`1-3,7`) |
| `--pdf-text` | `auto`(기본) / `always` / `never` |
| `-r, --recursive` | 하위 폴더까지 훑기 |

**이미지 보정**

| 옵션 | 설명 |
|---|---|
| `--no-preprocess` | 보정 없이 원본 그대로 |
| `--no-deskew` | 기울기 교정 끄기 |
| `--no-auto-rotate` | 90/180도 회전 감지 끄기 |
| `--binarize` | 흑백 이진화 |
| `--denoise` | 노이즈 제거 |

**문서 구성**

| 옵션 | 설명 |
|---|---|
| `--keep-line-breaks` | 줄바꿈 그대로 보존 |
| `--no-headings` / `--no-lists` | 제목/목록 자동 인식 끄기 |
| `--no-page-break` | 쪽 나눔 넣지 않기 |
| `--embed-image` | 원본 이미지도 문서에 넣기 |
| `--font-korean` / `--font-latin` | 글꼴 (기본 `맑은 고딕`) |
| `--font-size` / `--line-spacing` | 글자 크기(pt) / 줄 간격 |

## 웹사이트·어플리케이션으로 쓰기

Tesseract를 컴퓨터마다 깔지 않아도 되게, **서버 한 대에만 설치해 두고 브라우저로**
쓸 수 있습니다. 휴대폰으로 찍어 그 자리에서 문서로 바꿀 때 특히 편합니다.

```bash
pip install -e ".[web]"     # fastapi · uvicorn · python-multipart
scan2doc serve --open       # http://127.0.0.1:8000
```

같은 공유기에 있는 휴대폰에서도 쓰려면 주소를 열어 줍니다.

```bash
scan2doc serve --host 0.0.0.0 --port 8000
# 휴대폰 브라우저에서 http://<컴퓨터 IP>:8000
```

화면에서 하는 일은 CLI와 같습니다. 파일을 끌어다 놓고 → 형식과 언어를 고르고 →
변환 → 내려받기. 결과가 여러 개면 ZIP으로 한꺼번에 받을 수 있고, 인식된 글자를
미리 볼 수도 있습니다.

**어플리케이션으로 설치하기** — 이 화면은 PWA라서 브라우저 메뉴의
*홈 화면에 추가* / *앱으로 설치* 를 고르면 주소창 없는 앱처럼 열립니다.
아이폰은 Safari의 공유 → 홈 화면에 추가, 안드로이드·데스크톱 크롬은 주소창의 설치 단추입니다.

### serve 옵션

| 옵션 | 설명 |
|---|---|
| `--host` | 들을 주소 (기본 `127.0.0.1` — 이 컴퓨터에서만) |
| `--port` | 포트 번호 (기본 8000) |
| `--open` | 서버를 띄운 뒤 브라우저 열기 |
| `--workers` | 동시에 처리할 변환 개수 (기본 2) |
| `--max-upload-mb` | 파일 하나의 최대 크기 (기본 50MB) |
| `--workspace` | 올린 파일과 결과를 둘 폴더 (기본: 임시 폴더) |
| `--reload` | 코드가 바뀌면 서버 다시 띄우기 (개발용) |

### HTTP API

화면이 쓰는 API를 그대로 쓸 수 있습니다. 모바일 앱이나 다른 프로그램에서 부르면 됩니다.

```bash
# 올리고 작업 번호 받기
curl -X POST http://127.0.0.1:8000/api/jobs \
     -F "files=@계약서.jpg" \
     -F 'options={"formats":["docx","hwpx"],"language":"kor+eng"}'

# 진행 상황 (state: queued → running → done)
curl http://127.0.0.1:8000/api/jobs/<작업번호>

# 결과 내려받기
curl -OJ http://127.0.0.1:8000/api/jobs/<작업번호>/archive
```

자세한 규격과 서버 운영(백그라운드 실행, 리버스 프록시, 보안)은
[docs/WEB.md](docs/WEB.md)에 있습니다. 서버가 떠 있으면 `/api/docs` 에서
대화형 문서(OpenAPI)도 볼 수 있습니다.

## 파이썬에서 쓰기

```python
from pathlib import Path
from scan2doc import ConvertOptions, convert

options = ConvertOptions(
    formats=["docx", "hwpx"],
    output=Path("결과"),
    language="kor+eng",
    title="회의록",
)

for result in convert(["사진/"], options):
    print(f"{result.page_count}쪽, 신뢰도 {result.confidence:.0f}%")
    for path in result.outputs:
        print(" →", path)

    # 인식된 구조에 직접 접근할 수도 있습니다
    for page in result.document.pages:
        for block in page.blocks:
            print(block.kind.value, block.text)
```

## 어떻게 동작하나요

```
입력 파일  →  페이지 적재  →  이미지 보정  →  OCR  →  구조 복원  →  문서 작성
(inputs)      (LoadedPage)   (preprocess)  (ocr/)   (layout)      (writers/)
```

1. **적재** — 이미지·여러 장 TIFF·PDF를 모두 '쪽의 나열'로 바꿉니다.
   PDF에 이미 글자 레이어가 있으면 OCR을 건너뛰고 그대로 읽습니다(훨씬 정확).
2. **보정** — 회전을 먼저 바로잡고(90도 단위는 무손실), 기울기를 교정한 뒤
   필요하면 이진화·노이즈 제거를 합니다.
3. **OCR** — Tesseract를 한 번 실행해 좌표(TSV)와 문장(TXT)을 함께 받습니다.
   한국어는 TSV의 '낱말'이 음절 단위로 쪼개지는 일이 잦은데, 같은 실행의 문장 출력에는
   띄어쓰기가 살아 있어 두 결과를 줄 단위로 맞춰 붙입니다.
   짝이 맞지 않으면 글자 높이 대비 간격으로 어절을 복원합니다.
4. **구조 복원** — 글자 높이를 견주어 제목을 찾고, 글머리 기호를 떼어 목록으로 만들고,
   같은 문단의 줄을 이어 붙입니다(한국어는 어절 경계에서 줄이 바뀌므로 공백을 넣고,
   영어의 분철 하이픈은 다시 붙입니다).
5. **작성** — 공통 문서 모델을 각 형식으로 씁니다. `.hwpx`는 OWPML 규격대로 ZIP 안에
   XML을 직접 만들어 넣습니다(외부 라이브러리 없음).

## 개발

```bash
pip install -e ".[dev,preprocess,web]"
pytest                      # 전체 테스트
pytest -k not EndToEnd      # Tesseract 없이 돌릴 수 있는 것만
```

Tesseract와 한국어 글꼴이 있는 환경에서는 실제 한국어 이미지를 만들어
변환까지 확인하는 통합 테스트가 함께 돕니다.

```
src/scan2doc/
├── cli.py          명령줄 인터페이스
├── gui.py          tkinter 창
├── config.py       변환 옵션
├── model.py        문서 모델(Document/Page/Block/Line/Word)
├── inputs.py       이미지·PDF 적재
├── preprocess.py   기울기 교정·이진화
├── layout.py       낱말 → 문단 구조 복원
├── pipeline.py     전체 흐름
├── ocr/            OCR 엔진 (tesseract)
├── writers/        출력 형식 (docx, hwpx, hwpml, txt, md)
└── web/            웹사이트·어플리케이션 (HTTP API + 화면)
    ├── app.py      FastAPI 앱과 API
    ├── jobs.py     업로드·변환 작업 관리
    ├── options.py  웹에서 온 설정 검사
    ├── server.py   scan2doc serve
    └── static/     화면(HTML·CSS·JS)과 앱 설치 정보
```

새 OCR 엔진이나 출력 형식은 각각 `OcrEngine`, `DocumentWriter`를 상속해
`register()`로 등록하면 CLI·GUI에 자동으로 나타납니다.

### 브랜치 구조

파이프라인 단계마다 통합 브랜치를 하나씩 두고, **바꾼 파일에 따라 PR이 갈 브랜치가 정해집니다.**

| 브랜치 | 맡는 일 |
|---|---|
| `main` | 줄기 |
| `feature/inputs` | 입력 적재 |
| `feature/preprocess` | 이미지 보정 |
| `feature/ocr` | 문자 인식 |
| `feature/layout` | 구조 복원 |
| `feature/writers` | 문서 출력 |
| `feature/interface` | CLI·GUI |
| `feature/web` | 웹사이트·어플리케이션 |
| `feature/core` | 공통 뼈대 |

한 기능만 고쳤으면 그 기능 브랜치로, 여러 기능에 걸치거나 문서만 고쳤으면 `main`으로 보냅니다.
PR을 열면 자동으로 확인해 알려 주고, `main`이 바뀌면 모든 기능 브랜치에 자동으로 되먹입니다.
자세한 내용은 [docs/BRANCHING.md](docs/BRANCHING.md)와 [CONTRIBUTING.md](CONTRIBUTING.md)에 있습니다.

## 알려진 한계

- **표는 문단으로 풀립니다.** 표의 칸 구조는 복원하지 않고 글자만 순서대로 담습니다.
- **손글씨**는 Tesseract가 잘 읽지 못합니다. 인쇄된 글자를 기준으로 만들었습니다.
- **여러 단 문서**는 `--psm 3`을 주면 나아지지만, 복잡한 잡지 편집은 순서가 섞일 수 있습니다.
- **`.hwp`(이진 형식)로 직접 저장하지 않습니다.** 위 [한글(HWP) 파일에 대해](#한글hwp-파일에-대해)를 참고하세요.

## 라이선스

MIT

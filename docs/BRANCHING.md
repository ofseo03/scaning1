# 브랜치 구조

이 저장소는 **파이프라인 단계마다 통합 브랜치를 하나씩** 둡니다.
어떤 단계를 고쳤는지에 따라 PR이 갈 곳이 정해지고, 검증이 끝나면 `main`으로 모입니다.

```
                    ┌── feature/inputs ─────┐   입력 적재
                    ├── feature/preprocess ─┤   이미지 보정
                    ├── feature/ocr ────────┤   문자 인식
   main  ───────────┼── feature/layout ─────┼──────────────▶  main
   (줄기)           ├── feature/writers ────┤   문서 출력
                    ├── feature/interface ──┤   CLI·GUI
                    ├── feature/web ────────┤   웹사이트·앱
                    └── feature/core ───────┘   공통 뼈대
                         ▲                 │
                         └── 자동 되먹임 ──┘
                     (main이 바뀌면 모든 기능 브랜치에 즉시 반영)
```

## 브랜치별 담당 범위

| 브랜치 | 맡는 일 | 해당 파일 |
|---|---|---|
| `main` | 줄기. 배포되는 상태 | — |
| `feature/inputs` | 이미지·PDF를 쪽 단위로 읽어들이기 | `src/scan2doc/inputs.py` |
| `feature/preprocess` | 회전·기울기 교정, 이진화, 노이즈 제거 | `src/scan2doc/preprocess.py` |
| `feature/ocr` | OCR 엔진 어댑터 | `src/scan2doc/ocr/` |
| `feature/layout` | 낱말을 제목·문단·목록으로 복원 | `src/scan2doc/layout.py` |
| `feature/writers` | docx·hwpx·hwpml·txt·md 작성기 | `src/scan2doc/writers/` |
| `feature/interface` | CLI, GUI, 환경 점검 | `src/scan2doc/cli.py`, `gui.py`, `doctor.py` |
| `feature/web` | 웹 API, 웹 화면, 업로드 작업 관리 | `src/scan2doc/web/` |
| `feature/core` | 문서 모델, 설정, 파이프라인 | `src/scan2doc/model.py`, `config.py`, `pipeline.py`, `errors.py` |

`tests/`, `docs/`, `README.md`, `pyproject.toml`, `.github/` 는 **어느 기능에도 매이지 않습니다.**
기능 코드와 함께 바뀌면 그 기능 브랜치로 따라가고, 그것만 바뀌면 `main`으로 갑니다.

이 표의 실제 출처는 [`.github/scripts/branch_routing.py`](../.github/scripts/branch_routing.py) 입니다.
브랜치를 늘리거나 담당 범위를 바꾸려면 그 파일의 `FEATURES` 를 고치세요.
자동 검사와 동기화 워크플로가 모두 그 정의를 따라갑니다.

## PR은 어디로 보내나

세 가지 규칙이 전부입니다.

1. **한 기능만 고쳤다** → 그 기능 브랜치로
2. **여러 기능에 걸쳐 있다** → `main`으로 (단계를 가로지르는 변경은 줄기에서 합칩니다)
3. **기능 코드는 그대로고 문서·테스트·설정만 고쳤다** → `main`으로

예시:

| 바꾼 파일 | 갈 곳 |
|---|---|
| `src/scan2doc/ocr/tesseract.py`, `tests/test_ocr_tesseract.py` | `feature/ocr` |
| `src/scan2doc/writers/hwpx_writer.py` | `feature/writers` |
| `src/scan2doc/web/app.py`, `src/scan2doc/web/static/app.js` | `feature/web` |
| `src/scan2doc/ocr/base.py`, `src/scan2doc/writers/docx_writer.py` | `main` |
| `README.md` | `main` |

### 대상 브랜치는 알아서 옮겨집니다

**어느 브랜치를 대상으로 PR을 열든 상관없습니다.** `main`으로 열어 두면 됩니다.

PR을 열면 **PR 대상 브랜치 검사**가 바뀐 파일을 보고 갈 곳을 정한 뒤,
**base 브랜치를 직접 옮기고** 무엇을 했는지 댓글로 남깁니다.
코드를 다시 올릴 필요도, `Edit` 단추를 누를 필요도 없습니다.

```
PR 열기 (base: main)
  └─ src/scan2doc/ocr/tesseract.py 를 고쳤네
       └─ base 를 feature/ocr 로 옮김 + 댓글
```

옮기지 못하는 경우(대상 브랜치가 없거나 권한이 없을 때)에만 어디로 보내야
하는지 알려 주고 검사가 실패합니다. 그때는 `Edit` 단추로 직접 바꿔 주세요.

**옮기지 않기를 바란다면** PR에 `routing-override` 라벨을 붙이세요.
그 뒤로는 검사가 통째로 넘어가므로 대상 브랜치를 원하는 대로 둘 수 있습니다.

## 기능 브랜치 → main

기능 브랜치에 쌓인 변경은 준비가 되면 `main`으로 PR을 엽니다.

이런 **통합 PR은 검사가 손대지 않습니다.** PR이 올라온 브랜치(`head`)가
`main`이나 `feature/*` 이면 "쌓인 작업을 올리는 PR"로 보고 대상 브랜치를
그대로 둡니다. 파일만 보고 판단하면 `feature/ocr` → `main` PR에게
"`feature/ocr`로 가라"는 말이 안 되는 결론이 나오기 때문입니다.

## main → 기능 브랜치 (자동)

`main`에 무언가 들어오면 **기능 브랜치 동기화** 워크플로가 모든 기능 브랜치에
`main`을 자동으로 합쳐 넣습니다. 브랜치가 오래 뒤처져 나중에 큰 충돌이 나는 일을 막기 위해서입니다.

충돌이 나면 그 브랜치의 작업만 실패하고 나머지는 계속 진행합니다.
실패한 브랜치는 직접 합쳐 주세요:

```bash
git checkout feature/ocr
git merge origin/main      # 충돌 해결
git push
```

## 작업 시작하기

**`main`에서 시작해도 됩니다.** 대상 브랜치는 PR을 연 뒤 알아서 옮겨집니다.

```bash
# main 에서 작업용 브랜치를 파고
git checkout main && git pull
git checkout -b work/ocr-easyocr-engine

# 작업한 뒤 밀어 올리고 PR 을 연다 (대상은 main 이어도 된다)
git push -u origin work/ocr-easyocr-engine
```

`main`은 자동 되먹임 덕분에 모든 기능 브랜치의 조상이므로, `main`에서 딴
브랜치를 기능 브랜치로 보내도 diff에는 내가 고친 것만 나옵니다.

고칠 기능이 분명하다면 그 브랜치에서 출발하는 편이 더 자연스럽습니다.
그 브랜치에만 있고 아직 `main`에 없는 변경 위에서 작업하게 되기 때문입니다.

```bash
git checkout feature/ocr && git pull
git checkout -b work/ocr-easyocr-engine
```

## 왜 이렇게 하나

기능마다 통합 지점을 두면 **관련된 변경이 한곳에 모여** 함께 검증됩니다.
예를 들어 `.hwpx` 서식을 여러 번에 걸쳐 고칠 때, 각각을 `main`에 바로 넣는 대신
`feature/writers`에 모아 두고 한/글에서 실제로 열어 확인한 뒤 `main`으로 보낼 수 있습니다.

대신 브랜치가 오래 살아 있으면 서로 멀어진다는 대가가 따릅니다.
그래서 `main` → 기능 브랜치 되먹임을 자동으로 돌립니다.
**기능 브랜치는 되도록 짧게 유지하고, 검증이 끝나면 바로 `main`으로 보내 주세요.**

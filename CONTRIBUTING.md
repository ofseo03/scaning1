# 기여 안내

## 개발 환경

```bash
git clone https://github.com/ofseo03/scaning1.git
cd scaning1
pip install -e ".[dev,preprocess]"

# OCR 엔진 (Ubuntu/Debian 기준)
sudo apt install tesseract-ocr tesseract-ocr-kor

scan2doc doctor   # 설치 상태 점검
```

## 브랜치와 PR

**바꾼 파일에 따라 PR을 보낼 브랜치가 정해집니다.** 자세한 규칙은
[docs/BRANCHING.md](docs/BRANCHING.md)를 읽어 주세요. 요약하면:

- 한 기능만 고쳤으면 → 그 기능 브랜치 (`feature/ocr`, `feature/writers` 등)
- 여러 기능에 걸쳐 있거나 문서·설정만 고쳤으면 → `main`

어디로 보낼지 헷갈리면 그냥 PR을 여세요. 자동 검사가 알려 주고,
대상 브랜치는 PR을 연 뒤에도 `Edit` 단추로 바꿀 수 있습니다.

지금 바꾼 파일이 어디로 가는지 미리 확인할 수도 있습니다:

```bash
git diff --name-only origin/main... | \
  python3 .github/scripts/branch_routing.py --changed-from - --base main
```

## 테스트

```bash
pytest                      # 전체
pytest -k "not EndToEnd"    # Tesseract 없이 돌릴 수 있는 것만
```

Tesseract와 한국어 글꼴(`fonts-nanum` 등)이 있으면 실제 한국어 이미지를 만들어
변환까지 확인하는 통합 테스트가 함께 돕니다. 인식 품질에 영향을 주는 변경
(`ocr/`, `preprocess.py`, `layout.py`)을 했다면 이 테스트를 꼭 돌려 주세요.

## 코드에 대해

- 주석과 문서는 한국어로 씁니다. 식별자는 영어입니다.
- 새 OCR 엔진은 `OcrEngine`을, 새 출력 형식은 `DocumentWriter`를 상속하고
  `register()`로 등록하면 CLI와 GUI에 자동으로 나타납니다.
- 새 기능 영역을 만들었다면 `.github/scripts/branch_routing.py`의 `FEATURES`에
  추가해 주세요. 브랜치 목록과 자동 검사가 그 정의를 따라갑니다.

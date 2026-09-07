"""브라우저판(public/)의 자바스크립트가 파이썬 구현과 어긋나지 않는지 확인한다.

같은 사진에서 브라우저와 명령줄이 다른 문서를 내놓으면 곤란하므로,
두 구현이 같은 규칙을 쓰는지 node 로 직접 돌려 견준다.
node 가 없는 환경에서는 건너뛴다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not PUBLIC.is_dir(),
    reason="node 또는 public/ 없음",
)


def run_node(script: str) -> str:
    """ES 모듈 조각을 node 로 돌리고 표준 출력을 돌려준다."""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{result.stderr}")
    return result.stdout.strip()


LIB = (PUBLIC / "lib").as_posix()


class TestModulesLoad:
    @pytest.mark.parametrize("name", [
        "zip.js", "layout.js", "hwpx.js", "docx.js", "text.js", "ocr.js", "source.js",
    ])
    def test_모듈을_불러올_수_있다(self, name):
        # 모듈 최상단에서 브라우저 전용 API 를 쓰면 여기서 걸린다.
        run_node(f"await import('{LIB}/{name}');")

    def test_app과_index가_짝이_맞는다(self):
        html = (PUBLIC / "index.html").read_text(encoding="utf-8")
        app = (PUBLIC / "app.js").read_text(encoding="utf-8")
        for element_id in ("drop", "picker", "filelist", "formats", "run", "reset",
                           "status", "results", "preview", "notice"):
            assert f'id="{element_id}"' in html, f"{element_id} 가 index.html 에 없습니다"
            assert element_id in app, f"{element_id} 를 app.js 가 쓰지 않습니다"


class TestLayoutMatchesPython:
    """레이아웃 규칙이 파이썬 쪽과 같은 답을 내는지."""

    def test_낱말_잇기가_같다(self):
        from scan2doc.model import BBox, Word, join_words

        cases = [
            ([("규", 0, 20), ("정", 22, 20), ("은", 44, 20)], "규정은"),
            ([("문서", 0, 40), ("관리", 60, 40)], "문서 관리"),
            ([("제", 0, 40), ("1", 20, 20), ("조", 38, 20)], "제1조"),
            ([("Hello", 0, 50), ("world", 52, 50)], "Hello world"),
        ]
        js_input = json.dumps([
            [{"text": t, "x": x, "w": w, "h": 24} for t, x, w in words]
            for words, _ in cases
        ], ensure_ascii=False)
        out = run_node(
            f"import {{ joinWords }} from '{LIB}/layout.js';"
            f"const cases = {js_input};"
            "console.log(JSON.stringify(cases.map(joinWords)));"
        )
        js_results = json.loads(out)

        for (words, expected), js_result in zip(cases, js_results):
            py_result = join_words([
                Word(text=t, bbox=BBox(x, 0, w, 24), confidence=90) for t, x, w in words
            ])
            assert py_result == expected, f"파이썬: {py_result!r}"
            assert js_result == expected, f"자바스크립트: {js_result!r}"

    def test_줄_잇기가_같다(self):
        from scan2doc.model import join_lines

        cases = [
            (["문서 관리에 관한", "기본적인 사항을"], "문서 관리에 관한 기본적인 사항을"),
            (["inter-", "national"], "international"),
            (["漢字文書", "管理規程"], "漢字文書管理規程"),
        ]
        js_input = json.dumps([c[0] for c in cases], ensure_ascii=False)
        out = run_node(
            f"import {{ joinLines }} from '{LIB}/layout.js';"
            f"console.log(JSON.stringify({js_input}.map(joinLines)));"
        )
        for (lines, expected), js_result in zip(cases, json.loads(out)):
            assert join_lines(lines) == expected
            assert js_result == expected

    def test_목록_기호_판별이_같다(self):
        from scan2doc.layout import split_list_marker

        cases = ["- 첫째 항목", "1. 번호 항목", "(3) 괄호 번호", "가. 한글 번호",
                 "보통 문장입니다", "1.5배 증가"]
        out = run_node(
            f"import {{ splitListMarker }} from '{LIB}/layout.js';"
            f"const cases = {json.dumps(cases, ensure_ascii=False)};"
            "console.log(JSON.stringify(cases.map((t) => {"
            "  const r = splitListMarker(t);"
            "  return r ? [r.marker, r.rest, r.ordered] : null; })));"
        )
        for text, js_result in zip(cases, json.loads(out)):
            py_result = split_list_marker(text)
            py_list = list(py_result) if py_result else None
            assert py_list == js_result, f"{text!r}: 파이썬 {py_list} vs JS {js_result}"


class TestGeneratedFiles:
    """브라우저가 만든 문서가 파이썬 것과 같은 구조인지."""

    DOC_JS = """
      const doc = { title: '테스트 문서', pages: [
        { blocks: [
          { kind: 'heading', level: 1, text: '제1장 <총칙>', listMarker: '', ordered: false },
          { kind: 'paragraph', level: 0, text: '본문 & 내용입니다.', listMarker: '', ordered: false },
          { kind: 'list_item', level: 0, text: '전자 보관', listMarker: '-', ordered: false } ] },
        { blocks: [{ kind: 'paragraph', level: 0, text: '둘째 쪽', listMarker: '', ordered: false }] } ] };
    """

    def build(self, tmp_path: Path, module: str, func: str, name: str) -> Path:
        target = tmp_path / name
        run_node(
            f"import {{ {func} }} from '{LIB}/{module}';"
            "import { writeFileSync } from 'node:fs';"
            + self.DOC_JS +
            f"writeFileSync({json.dumps(str(target))}, await {func}(doc));"
        )
        return target

    def test_hwpx가_파이썬과_같은_구조다(self, tmp_path):
        js_path = self.build(tmp_path, "hwpx.js", "buildHwpx", "js.hwpx")

        from scan2doc.config import ConvertOptions
        from scan2doc.model import Block, BlockKind, Document, Page
        from scan2doc.writers.hwpx_writer import HwpxWriter

        py_doc = Document(title="테스트 문서", pages=[
            Page(index=0, blocks=[
                Block(kind=BlockKind.HEADING, level=1, text_override="제1장 <총칙>"),
                Block(text_override="본문 & 내용입니다."),
                Block(kind=BlockKind.LIST_ITEM, list_marker="-", text_override="전자 보관"),
            ]),
            Page(index=1, blocks=[Block(text_override="둘째 쪽")]),
        ])
        py_path = tmp_path / "py.hwpx"
        HwpxWriter().write(py_doc, py_path, ConvertOptions())

        with zipfile.ZipFile(js_path) as js, zipfile.ZipFile(py_path) as py:
            assert js.testzip() is None
            assert sorted(js.namelist()) == sorted(py.namelist())
            # mimetype 은 맨 앞에 무압축으로 — OWPML 의 요구 사항이다.
            first = js.infolist()[0]
            assert first.filename == "mimetype"
            assert first.compress_type == zipfile.ZIP_STORED
            for name in js.namelist():
                if name.endswith((".xml", ".hpf", ".rdf")):
                    ET.fromstring(js.read(name))
            # 선언한 itemCnt 와 실제 항목 수가 맞아야 한/글이 연다.
            root = ET.fromstring(js.read("Contents/header.xml"))
            for element in root.iter():
                declared = element.get("itemCnt")
                if declared is not None:
                    assert len(list(element)) == int(declared), element.tag
            section = js.read("Contents/section0.xml").decode()
            assert "제1장 &lt;총칙&gt;" in section
            assert 'pageBreak="1"' in section
            assert section.count("<hp:p ") == py.read(
                "Contents/section0.xml").decode().count("<hp:p ")

    def test_docx를_워드_라이브러리가_연다(self, tmp_path):
        docx = pytest.importorskip("docx")
        path = self.build(tmp_path, "docx.js", "buildDocx", "js.docx")

        with zipfile.ZipFile(path) as zf:
            assert zf.testzip() is None
            for name in zf.namelist():
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(zf.read(name))

        opened = docx.Document(str(path))
        texts = [p.text for p in opened.paragraphs if p.text.strip()]
        assert "테스트 문서" in texts
        assert "제1장 <총칙>" in texts
        assert any("전자 보관" in t for t in texts)
        # 한글이 깨지지 않으려면 eastAsia 글꼴이 있어야 한다.
        assert 'w:eastAsia="맑은 고딕"' in opened.paragraphs[1]._element.xml

    def test_zip이_손상되지_않는다(self, tmp_path):
        target = tmp_path / "plain.zip"
        run_node(
            f"import {{ makeZip }} from '{LIB}/zip.js';"
            "import { writeFileSync } from 'node:fs';"
            "const bytes = await makeZip(["
            "  { name: 'mimetype', data: 'application/hwp+zip', store: true },"
            "  { name: 'a/b.txt', data: '한글 내용'.repeat(200) }]);"
            f"writeFileSync({json.dumps(str(target))}, bytes);"
        )
        with zipfile.ZipFile(target) as zf:
            assert zf.testzip() is None
            assert zf.read("mimetype").decode() == "application/hwp+zip"
            assert zf.read("a/b.txt").decode() == "한글 내용" * 200
            assert zf.getinfo("a/b.txt").compress_type == zipfile.ZIP_DEFLATED

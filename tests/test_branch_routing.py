"""PR을 어느 브랜치로 보낼지 정하는 규칙.

브랜치 구조가 코드와 어긋나면(모듈이 새로 생겼는데 담당 브랜치가 없다든지)
여기서 잡힌다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from branch_routing import (
    ALL_BRANCHES,
    FEATURES,
    TRUNK,
    Decision,
    feature_for,
    main,
    report,
    route,
)

ROOT = Path(__file__).resolve().parents[1]


class TestFeatureFor:
    @pytest.mark.parametrize("path,expected", [
        ("src/scan2doc/inputs.py", "feature/inputs"),
        ("src/scan2doc/preprocess.py", "feature/preprocess"),
        ("src/scan2doc/ocr/tesseract.py", "feature/ocr"),
        ("src/scan2doc/ocr/__init__.py", "feature/ocr"),
        ("src/scan2doc/layout.py", "feature/layout"),
        ("src/scan2doc/writers/hwpx_writer.py", "feature/writers"),
        ("src/scan2doc/cli.py", "feature/interface"),
        ("src/scan2doc/gui.py", "feature/interface"),
        ("src/scan2doc/web/app.py", "feature/web"),
        ("src/scan2doc/web/static/app.js", "feature/web"),
        ("src/scan2doc/model.py", "feature/core"),
        ("src/scan2doc/pipeline.py", "feature/core"),
    ])
    def test_파일이_맡은_브랜치를_찾는다(self, path, expected):
        assert feature_for(path) == expected

    @pytest.mark.parametrize("path", [
        "README.md", "tests/test_model.py", "pyproject.toml",
        ".github/workflows/ci.yml", "docs/BRANCHING.md", "",
    ])
    def test_기능에_매이지_않는_파일은_None(self, path):
        assert feature_for(path) is None

    def test_윈도우_경로_구분자도_받아준다(self):
        assert feature_for("src\\scan2doc\\layout.py") == "feature/layout"

    def test_앞에_붙은_점_슬래시를_떼어낸다(self):
        assert feature_for("./src/scan2doc/layout.py") == "feature/layout"

    def test_비슷한_이름에_속지_않는다(self):
        # inputs.py 는 등록돼 있지만 inputs_extra.py 는 아니다.
        assert feature_for("src/scan2doc/inputs_extra.py") is None


class TestRoute:
    def test_한_기능만_고치면_그_브랜치로(self):
        decision = route(["src/scan2doc/ocr/tesseract.py"])
        assert decision.target == "feature/ocr"

    def test_테스트와_문서가_같이_바뀌어도_기능을_따라간다(self):
        decision = route([
            "src/scan2doc/ocr/tesseract.py",
            "tests/test_ocr_tesseract.py",
            "README.md",
        ])
        assert decision.target == "feature/ocr"
        assert "tests/test_ocr_tesseract.py" in decision.unmatched

    def test_여러_기능에_걸치면_줄기로(self):
        decision = route([
            "src/scan2doc/ocr/base.py",
            "src/scan2doc/writers/docx_writer.py",
        ])
        assert decision.target == TRUNK
        assert decision.touched == ["feature/ocr", "feature/writers"]

    def test_웹과_CLI를_함께_고치면_줄기로(self):
        # 웹 서버는 CLI(scan2doc serve)로도 띄우므로 함께 바뀌는 일이 잦다.
        decision = route(["src/scan2doc/web/app.py", "src/scan2doc/cli.py"])
        assert decision.target == TRUNK
        assert decision.touched == ["feature/interface", "feature/web"]

    def test_문서만_고치면_줄기로(self):
        assert route(["README.md", "docs/BRANCHING.md"]).target == TRUNK

    def test_바뀐_파일이_없으면_줄기로(self):
        assert route([]).target == TRUNK

    def test_건드린_기능은_파이프라인_순서로_나온다(self):
        decision = route([
            "src/scan2doc/writers/base.py",
            "src/scan2doc/inputs.py",
            "src/scan2doc/ocr/base.py",
        ])
        assert decision.touched == ["feature/inputs", "feature/ocr", "feature/writers"]

    @pytest.mark.parametrize("base,expected", [
        ("feature/ocr", True),
        ("refs/heads/feature/ocr", True),
        ("origin/feature/ocr", True),
        ("main", False),
    ])
    def test_브랜치_이름_표기를_맞춰_비교한다(self, base, expected):
        assert route(["src/scan2doc/ocr/base.py"]).matches(base) is expected


class TestReport:
    def test_맞으면_통과라고_알려준다(self):
        body = report(route(["README.md"]), "main")
        assert "대상 브랜치가 맞습니다" in body

    def test_틀리면_갈_곳을_알려준다(self):
        body = report(route(["src/scan2doc/layout.py"]), "main")
        assert "feature/layout" in body
        assert "routing-override" in body  # 넘어가는 방법도 함께 안내


class TestCli:
    def test_맞으면_0으로_끝난다(self, capsys):
        assert main(["--base", "main", "README.md"]) == 0

    def test_틀리면_1로_끝난다(self, capsys):
        assert main(["--base", "main", "src/scan2doc/layout.py"]) == 1

    def test_목록을_출력한다(self, capsys):
        assert main(["--list"]) == 0
        out = capsys.readouterr().out
        assert all(name in out for name, _, _ in FEATURES)

    def test_파일에서_목록을_읽는다(self, tmp_path, capsys):
        listing = tmp_path / "changed.txt"
        listing.write_text("src/scan2doc/ocr/base.py\n", encoding="utf-8")
        assert main(["--base", "feature/ocr", "--changed-from", str(listing)]) == 0

    def test_안내문을_파일로_저장한다(self, tmp_path, capsys):
        out = tmp_path / "comment.md"
        main(["--base", "main", "src/scan2doc/layout.py", "--comment-out", str(out)])
        assert "feature/layout" in out.read_text(encoding="utf-8")


class TestRulesMatchTheCode:
    """규칙이 실제 저장소 구조와 어긋나지 않는지 확인한다."""

    def test_규칙에_적힌_경로가_실제로_있다(self):
        for name, _, patterns in FEATURES:
            for pattern in patterns:
                assert (ROOT / pattern).exists(), f"{name}: {pattern} 가 없습니다"

    def test_모든_소스_파일이_어느_한_브랜치에_속한다(self):
        # 새 모듈을 만들고 규칙에 넣는 것을 잊으면 여기서 걸린다.
        orphans = [
            str(path.relative_to(ROOT))
            for path in sorted((ROOT / "src" / "scan2doc").rglob("*.py"))
            if feature_for(str(path.relative_to(ROOT))) is None
        ]
        assert not orphans, (
            "담당 브랜치가 없는 파일입니다. "
            ".github/scripts/branch_routing.py 의 FEATURES 에 넣어 주세요: " + ", ".join(orphans)
        )

    def test_브랜치_이름이_겹치지_않는다(self):
        assert len(set(ALL_BRANCHES)) == len(ALL_BRANCHES)

    def test_한_파일이_두_브랜치에_속하지_않는다(self):
        seen: dict[str, str] = {}
        for name, _, patterns in FEATURES:
            for pattern in patterns:
                assert pattern not in seen, f"{pattern} 가 {seen.get(pattern)} 와 {name} 양쪽에 있습니다"
                seen[pattern] = name

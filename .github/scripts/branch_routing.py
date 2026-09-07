#!/usr/bin/env python3
"""바뀐 파일을 보고 PR이 어느 브랜치로 가야 하는지 정한다.

파이프라인 단계마다 통합 브랜치를 하나씩 두고, 그 단계의 코드를 고친 PR은
해당 브랜치로 보낸다. 여러 단계에 걸친 변경만 main으로 모은다.

    python3 .github/scripts/branch_routing.py --base main --changed-from files.txt
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

#: 모든 기능 브랜치가 갈라져 나오고 다시 모이는 줄기
TRUNK = "main"

#: (브랜치, 설명, 이 브랜치가 맡는 경로들)
#: 경로가 "/"로 끝나면 그 폴더 아래 전부를 뜻한다.
FEATURES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "feature/inputs",
        "입력 적재 — 이미지·PDF를 쪽 단위로 읽어들이는 부분",
        ("src/scan2doc/inputs.py",),
    ),
    (
        "feature/preprocess",
        "이미지 보정 — 회전·기울기 교정, 이진화, 노이즈 제거",
        ("src/scan2doc/preprocess.py",),
    ),
    (
        "feature/ocr",
        "문자 인식 — OCR 엔진 어댑터",
        ("src/scan2doc/ocr/",),
    ),
    (
        "feature/layout",
        "구조 복원 — 낱말을 제목·문단·목록으로 되살리는 부분",
        ("src/scan2doc/layout.py",),
    ),
    (
        "feature/writers",
        "문서 출력 — docx·hwpx·hwpml·txt·md 작성기",
        ("src/scan2doc/writers/",),
    ),
    (
        "feature/interface",
        "사용자 인터페이스 — CLI, GUI, 환경 점검",
        (
            "src/scan2doc/cli.py",
            "src/scan2doc/gui.py",
            "src/scan2doc/doctor.py",
        ),
    ),
    (
        "feature/core",
        "공통 뼈대 — 문서 모델, 설정, 파이프라인",
        (
            "src/scan2doc/__init__.py",
            "src/scan2doc/__main__.py",
            "src/scan2doc/config.py",
            "src/scan2doc/errors.py",
            "src/scan2doc/model.py",
            "src/scan2doc/pipeline.py",
        ),
    ),
)

FEATURE_BRANCHES: tuple[str, ...] = tuple(name for name, _, _ in FEATURES)
DESCRIPTIONS: dict[str, str] = {name: desc for name, desc, _ in FEATURES}
ALL_BRANCHES: tuple[str, ...] = (TRUNK, *FEATURE_BRANCHES)


@dataclass
class Decision:
    """이 PR이 어디로 가야 하는지에 대한 판단."""

    target: str
    reason: str
    touched: list[str] = field(default_factory=list)
    """이 PR이 건드린 기능 브랜치들."""

    unmatched: list[str] = field(default_factory=list)
    """어느 기능에도 속하지 않는 파일들(테스트·문서·설정 등)."""

    def matches(self, base: str) -> bool:
        return _normalize(base) == self.target


def _normalize(ref: str) -> str:
    """refs/heads/main, origin/main 같은 표기를 브랜치 이름으로 맞춘다."""
    ref = ref.strip()
    for prefix in ("refs/heads/", "origin/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    return ref


def feature_for(path: str) -> str | None:
    """파일 하나가 속한 기능 브랜치. 어디에도 없으면 None."""
    path = path.strip().replace("\\", "/").lstrip("./")
    if not path:
        return None
    for name, _, patterns in FEATURES:
        for pattern in patterns:
            if pattern.endswith("/"):
                if path.startswith(pattern):
                    return name
            elif path == pattern:
                return name
    return None


def route(paths: list[str]) -> Decision:
    """바뀐 파일 목록으로 갈 곳을 정한다.

    - 한 기능만 건드렸으면 그 기능 브랜치로
    - 여러 기능에 걸쳐 있으면 main으로
    - 기능 코드를 건드리지 않았으면(문서·테스트·설정만) main으로
    """
    touched: list[str] = []
    unmatched: list[str] = []
    for path in paths:
        name = feature_for(path)
        if name is None:
            if path.strip():
                unmatched.append(path.strip())
        elif name not in touched:
            touched.append(name)

    # 선언 순서(파이프라인 순서)대로 정렬해 메시지를 읽기 쉽게 한다.
    touched.sort(key=FEATURE_BRANCHES.index)

    if len(touched) == 1:
        return Decision(
            target=touched[0],
            reason=f"{DESCRIPTIONS[touched[0]]} 한 곳만 바뀌었습니다.",
            touched=touched,
            unmatched=unmatched,
        )
    if len(touched) > 1:
        return Decision(
            target=TRUNK,
            reason=(
                "여러 기능에 걸친 변경입니다 ("
                + ", ".join(touched)
                + "). 이런 PR은 줄기에서 합칩니다."
            ),
            touched=touched,
            unmatched=unmatched,
        )
    return Decision(
        target=TRUNK,
        reason="기능 코드가 바뀌지 않았습니다(문서·테스트·설정만).",
        touched=touched,
        unmatched=unmatched,
    )


def report(decision: Decision, base: str) -> str:
    """PR에 남길 안내문(마크다운)."""
    base = _normalize(base)
    if decision.matches(base):
        lines = [
            f"✅ **대상 브랜치가 맞습니다** — `{base}`",
            "",
            decision.reason,
        ]
    else:
        lines = [
            "### 🔀 대상 브랜치를 바꿔 주세요",
            "",
            f"| | |",
            f"|---|---|",
            f"| 지금 대상 | `{base}` |",
            f"| 가야 할 곳 | **`{decision.target}`** |",
            "",
            decision.reason,
            "",
            "GitHub의 PR 제목 옆 **Edit** 단추를 누르면 대상 브랜치를 바꿀 수 있습니다. "
            "코드를 다시 올릴 필요는 없습니다.",
            "",
            "이 판단이 맞지 않다면 PR에 `routing-override` 라벨을 붙이면 검사를 넘어갑니다.",
        ]

    if decision.touched:
        lines += ["", "**건드린 기능**"]
        lines += [f"- `{name}` — {DESCRIPTIONS[name]}" for name in decision.touched]
    lines += ["", "<sub>브랜치 규칙은 저장소의 `docs/BRANCHING.md` 에 있습니다.</sub>"]
    return "\n".join(lines)


def _read_paths(args: argparse.Namespace) -> list[str]:
    if args.changed_from:
        if args.changed_from == "-":
            return sys.stdin.read().splitlines()
        with open(args.changed_from, encoding="utf-8") as handle:
            return handle.read().splitlines()
    return args.paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PR이 가야 할 브랜치를 정합니다.")
    parser.add_argument("paths", nargs="*", help="바뀐 파일 경로")
    parser.add_argument("--changed-from", metavar="파일",
                        help="바뀐 파일 목록을 담은 파일('-'이면 표준 입력)")
    parser.add_argument("--base", help="현재 PR의 대상 브랜치")
    parser.add_argument("--comment-out", metavar="파일",
                        help="안내문을 이 파일에 저장")
    parser.add_argument("--list", action="store_true", help="브랜치 목록만 출력")
    args = parser.parse_args(argv)

    if args.list:
        for name, desc, _ in FEATURES:
            print(f"{name}\t{desc}")
        return 0
    if not args.base:
        parser.error("--base 가 필요합니다.")

    decision = route(_read_paths(args))
    body = report(decision, args.base)
    print(body)
    if args.comment_out:
        with open(args.comment_out, "w", encoding="utf-8") as handle:
            handle.write(body)
    return 0 if decision.matches(args.base) else 1


if __name__ == "__main__":
    raise SystemExit(main())

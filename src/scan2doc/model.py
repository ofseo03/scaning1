"""스캔 결과를 표현하는 중간 문서 모델.

OCR 엔진과 출력 포맷(Word/HWP/...) 사이를 잇는 공통 표현이다.
엔진이 무엇이든 이 모델로 변환되고, 작성기(writer)는 이 모델만 본다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Iterable, Iterator


class BlockKind(str, Enum):
    """문단 블록의 종류."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    IMAGE = "image"


@dataclass(frozen=True)
class BBox:
    """이미지 좌표계(픽셀) 기준 사각형."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @staticmethod
    def union(boxes: Iterable["BBox"]) -> "BBox":
        boxes = list(boxes)
        if not boxes:
            return BBox(0, 0, 0, 0)
        x0 = min(b.x for b in boxes)
        y0 = min(b.y for b in boxes)
        x1 = max(b.right for b in boxes)
        y1 = max(b.bottom for b in boxes)
        return BBox(x0, y0, x1 - x0, y1 - y0)


@dataclass
class Word:
    """OCR이 인식한 낱말 하나."""

    text: str
    bbox: BBox
    confidence: float = -1.0


@dataclass
class Line:
    """같은 줄에 있는 낱말의 묶음."""

    words: list[Word] = field(default_factory=list)
    raw_text: str | None = None
    """OCR 엔진이 직접 알려 준 줄 문장(띄어쓰기가 이미 맞춰진 것)."""

    @property
    def text(self) -> str:
        if self.raw_text is not None:
            return self.raw_text.strip()
        return join_words(self.words)

    @property
    def bbox(self) -> BBox:
        return BBox.union(w.bbox for w in self.words)

    @property
    def confidence(self) -> float:
        scored = [w.confidence for w in self.words if w.confidence >= 0]
        return sum(scored) / len(scored) if scored else -1.0

    @property
    def height(self) -> int:
        """대문자/글자 높이의 대표값. 이상치에 강하도록 중앙값을 쓴다."""
        heights = sorted(w.bbox.height for w in self.words if w.text.strip())
        if not heights:
            return 0
        return heights[len(heights) // 2]


@dataclass
class Block:
    """하나의 문단(또는 제목/목록 항목)."""

    lines: list[Line] = field(default_factory=list)
    kind: BlockKind = BlockKind.PARAGRAPH
    level: int = 0
    """제목이면 1~3단계, 목록이면 들여쓰기 깊이."""

    list_marker: str = ""
    """목록 항목에서 떼어낸 기호나 번호(예: '-', '1.', '가.')."""

    ordered: bool = False
    text_override: str | None = None
    """레이아웃 재구성이 이미 끝난 텍스트(PDF 텍스트 레이어 등)."""

    @property
    def bbox(self) -> BBox:
        return BBox.union(line.bbox for line in self.lines)

    @property
    def confidence(self) -> float:
        scored = [line.confidence for line in self.lines if line.confidence >= 0]
        return sum(scored) / len(scored) if scored else -1.0

    @property
    def text(self) -> str:
        if self.text_override is not None:
            return self.text_override
        return join_lines(line.text for line in self.lines)

    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass
class Page:
    """원본 한 쪽(이미지 한 장 또는 PDF 한 페이지)."""

    index: int
    blocks: list[Block] = field(default_factory=list)
    width: int = 0
    height: int = 0
    dpi: int = 0
    source: str = ""
    source_page: int = 1
    image_path: str | None = None
    """미리보기용으로 저장해 둔 페이지 이미지 경로(--embed-image 옵션)."""

    engine: str = ""
    rotation: int = 0
    skew: float = 0.0

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if not b.is_empty())

    @property
    def confidence(self) -> float:
        scored = [b.confidence for b in self.blocks if b.confidence >= 0]
        return sum(scored) / len(scored) if scored else -1.0

    @property
    def word_count(self) -> int:
        return sum(len(line.words) for b in self.blocks for line in b.lines)


@dataclass
class Document:
    """변환 대상 전체."""

    title: str = ""
    pages: list[Page] = field(default_factory=list)
    language: str = "kor+eng"
    meta: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator[Page]:
        return iter(self.pages)

    def __len__(self) -> int:
        return len(self.pages)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def confidence(self) -> float:
        scored = [p.confidence for p in self.pages if p.confidence >= 0]
        return sum(scored) / len(scored) if scored else -1.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Enum -> 문자열, 그리고 파생 속성(text)을 함께 담아 디버깅을 쉽게 한다.
        for page, page_data in zip(self.pages, data["pages"]):
            for block, block_data in zip(page.blocks, page_data["blocks"]):
                block_data["kind"] = block.kind.value
                block_data["text"] = block.text
        return data

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# --- 줄 이어붙이기 -------------------------------------------------------

#: 글자 높이 대비 이 비율보다 간격이 넓으면 띄어쓰기로 본다
WORD_GAP_RATIO = 0.42

_CJK_RANGES = (
    (0xAC00, 0xD7A3),   # 한글 음절
    (0x1100, 0x11FF),   # 한글 자모
    (0x3130, 0x318F),   # 호환 자모
    (0x4E00, 0x9FFF),   # 한자
    (0x3040, 0x30FF),   # 가나
    (0xFF00, 0xFFEF),   # 전각
)


def is_cjk(ch: str) -> bool:
    """한글·한자·가나처럼 글자 폭이 일정한 동아시아 문자인지."""
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def is_hangul(ch: str) -> bool:
    """한글 음절 또는 자모인지."""
    code = ord(ch)
    return 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F


def join_words(words: list["Word"]) -> str:
    """낱말 사이 간격을 보고 띄어쓸지 붙일지 정한다.

    한국어에서 OCR은 한 어절을 음절 단위로 쪼개 놓는 일이 잦다.
    글자 높이에 견준 가로 간격이 좁으면 같은 어절로 보고 붙인다.
    """
    parts: list[str] = []
    real = [w for w in words if w.text.strip()]
    if not real:
        return ""

    heights = sorted(w.bbox.height for w in real)
    height = heights[len(heights) // 2] or max(heights)
    threshold = max(3.0, height * WORD_GAP_RATIO)

    parts.append(real[0].text)
    for prev, cur in zip(real, real[1:]):
        gap = cur.bbox.x - prev.bbox.right
        # 한쪽이라도 붙여 쓰는 문자면 간격으로 판단한다.
        # '제1조', '5년'처럼 숫자가 어절 안에 섞이는 경우까지 살리기 위해서다.
        touching_cjk = is_cjk(prev.text[-1]) or is_cjk(cur.text[0])
        if not touching_cjk or gap >= threshold:
            parts.append(" ")
        parts.append(cur.text)
    return "".join(parts).strip()


def join_lines(lines: Iterable[str]) -> str:
    """한 문단 안의 여러 줄을 자연스러운 한 문단으로 잇는다.

    - 영문은 공백으로 잇고, 줄 끝 하이픈은 이어붙이기(단어 분철)로 처리한다.
    - 한글·한자처럼 공백 없이 이어지는 문자끼리는 공백 없이 붙인다.
    """
    result = ""
    for raw in lines:
        piece = raw.strip()
        if not piece:
            continue
        if not result:
            result = piece
            continue
        prev = result[-1]
        nxt = piece[0]
        if prev == "-" and (nxt.isalpha() and not is_cjk(nxt)):
            result = result[:-1] + piece      # 분철된 영단어 복원
        elif is_cjk(prev) and is_cjk(nxt) and not (is_hangul(prev) or is_hangul(nxt)):
            result += piece                   # 한자·가나는 붙여 쓴다
        else:
            # 한국어는 대개 어절 경계에서 줄이 바뀌므로 공백을 넣는다.
            result += " " + piece
    return result

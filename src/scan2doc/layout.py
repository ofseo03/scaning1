"""OCR 낱말 목록을 문단 구조로 되살리는 단계.

Tesseract는 낱말마다 (블록, 문단, 줄) 번호와 좌표를 함께 주므로,
그 정보로 제목·목록·문단을 어느 정도 복원할 수 있다.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from .config import ConvertOptions
from .model import BBox, Block, BlockKind, Line, Word

#: 글머리 기호로 쓰이는 문자들
BULLET_CHARS = "-–—•·‣▪▫◦○●■□▶＊*"

_BULLET_RE = re.compile(rf"^\s*([{re.escape(BULLET_CHARS)}])\s+(?=\S)")
_ORDERED_RES = (
    re.compile(r"^\s*(\(?\d{1,3}[.)])\s+(?=\S)"),          # 1. / 1) / (1)
    re.compile(r"^\s*([①-⑳㉑-㉟])\s*(?=\S)"),               # ① ② …
    re.compile(r"^\s*([가-힣][.)])\s+(?=\S)"),              # 가. 나) …
    re.compile(r"^\s*(\(?[ivxIVX]{1,4}[.)])\s+(?=\S)"),    # i. ii) …
    re.compile(r"^\s*([A-Za-z][.)])\s+(?=\S)"),            # A. b) …
)

#: 제목으로 볼 최소 글자 높이 비율(본문 대비)
HEADING_RATIO_L3 = 1.22
HEADING_RATIO_L2 = 1.45
HEADING_RATIO_L1 = 1.8
#: 제목은 보통 짧다 — 이 글자 수를 넘으면 본문으로 본다
HEADING_MAX_CHARS = 90


@dataclass
class WordRecord:
    """OCR 엔진이 돌려준 낱말 하나(그룹 번호 포함)."""

    text: str
    bbox: BBox
    confidence: float
    block_num: int
    par_num: int
    line_num: int
    line_text: str | None = None
    """엔진이 알려 준 줄 전체 문장(있으면 띄어쓰기를 그대로 쓴다)."""


def build_blocks(records: list[WordRecord], options: ConvertOptions) -> list[Block]:
    """낱말 목록 → 문단 블록 목록."""
    lines = _group_lines(records)
    if not lines:
        return []

    if options.keep_line_breaks:
        blocks = [Block(lines=[line]) for line, _ in lines if line.text.strip()]
    else:
        blocks = _group_paragraphs(lines)

    blocks = [b for b in blocks if not b.is_empty()]
    if not blocks:
        return []

    if options.detect_headings:
        blocks = classify_headings(blocks)
    if options.detect_lists:
        blocks = classify_list_blocks(blocks)
    return blocks


def _group_lines(records: list[WordRecord]) -> list[tuple[Line, tuple[int, int]]]:
    """(블록, 문단, 줄) 번호로 낱말을 줄 단위로 묶는다."""
    grouped: dict[tuple[int, int, int], Line] = {}
    order: list[tuple[int, int, int]] = []

    for rec in records:
        if not rec.text.strip():
            continue
        key = (rec.block_num, rec.par_num, rec.line_num)
        if key not in grouped:
            grouped[key] = Line(raw_text=rec.line_text)
            order.append(key)
        grouped[key].words.append(
            Word(text=rec.text, bbox=rec.bbox, confidence=rec.confidence)
        )

    return [(grouped[k], (k[0], k[1])) for k in order]


def _group_paragraphs(lines: list[tuple[Line, tuple[int, int]]]) -> list[Block]:
    """같은 (블록, 문단)에 속한 줄들을 한 문단으로 묶는다."""
    blocks: list[Block] = []
    current_key: tuple[int, int] | None = None
    current: Block | None = None

    for line, key in lines:
        # OCR이 여러 목록 항목을 한 문단으로 묶어 놓는 일이 잦다.
        # 글머리 기호로 시작하는 줄은 언제나 새 항목으로 끊는다.
        starts_item = split_list_marker(line.text) is not None
        if key != current_key or current is None or starts_item:
            current = Block()
            blocks.append(current)
            current_key = key
        current.lines.append(line)
    return blocks


def classify_headings(blocks: list[Block]) -> list[Block]:
    """본문 글자 크기와 비교해 제목을 찾아낸다."""
    heights = [
        line.height
        for block in blocks
        for line in block.lines
        if line.height > 0 and line.text.strip()
    ]
    if len(heights) < 3:
        return blocks

    body_height = statistics.median(heights)
    if body_height <= 0:
        return blocks

    for block in blocks:
        if len(block.lines) > 2:
            continue  # 여러 줄짜리는 본문일 가능성이 높다
        text = block.text.strip()
        if not text or len(text) > HEADING_MAX_CHARS:
            continue
        block_height = statistics.median(
            [line.height for line in block.lines if line.height > 0] or [0]
        )
        if block_height <= 0:
            continue
        ratio = block_height / body_height
        if ratio >= HEADING_RATIO_L1:
            block.kind, block.level = BlockKind.HEADING, 1
        elif ratio >= HEADING_RATIO_L2:
            block.kind, block.level = BlockKind.HEADING, 2
        elif ratio >= HEADING_RATIO_L3:
            block.kind, block.level = BlockKind.HEADING, 3
    return blocks


def split_list_marker(text: str) -> tuple[str, str, bool] | None:
    """글머리 기호/번호를 떼어낸다. -> (기호, 남은 본문, 번호목록 여부)"""
    match = _BULLET_RE.match(text)
    if match:
        return match.group(1), text[match.end():].strip(), False
    for pattern in _ORDERED_RES:
        match = pattern.match(text)
        if match:
            rest = text[match.end():].strip()
            if rest:
                return match.group(1), rest, True
    return None


def classify_list_blocks(blocks: list[Block]) -> list[Block]:
    """글머리 기호로 시작하는 문단을 목록 항목으로 표시한다."""
    for block in blocks:
        if block.kind is BlockKind.HEADING:
            continue
        text = block.text.strip()
        parsed = split_list_marker(text)
        if not parsed:
            continue
        marker, rest, ordered = parsed
        block.kind = BlockKind.LIST_ITEM
        block.list_marker = marker
        block.ordered = ordered
        block.text_override = rest
    return blocks


def assign_list_levels(blocks: list[Block], page_left: int, unit: float) -> list[Block]:
    """목록 항목의 들여쓰기 깊이를 x좌표로 추정한다(0~3단계)."""
    if unit <= 0:
        return blocks
    for block in blocks:
        if block.kind is not BlockKind.LIST_ITEM or not block.lines:
            continue
        offset = block.bbox.x - page_left
        block.level = max(0, min(3, int(round(offset / (unit * 2)))))
    return blocks

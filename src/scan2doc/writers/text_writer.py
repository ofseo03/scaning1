"""일반 텍스트와 마크다운 출력."""

from __future__ import annotations

from pathlib import Path

from ..config import ConvertOptions
from ..model import BlockKind, Document
from .base import DocumentWriter


class TextWriter(DocumentWriter):
    name = "txt"
    extension = ".txt"
    description = "일반 텍스트"

    def write(self, document: Document, path: Path, options: ConvertOptions) -> Path:
        chunks: list[str] = []
        for page in document.pages:
            for block in page.blocks:
                if block.is_empty():
                    continue
                if block.kind is BlockKind.LIST_ITEM:
                    chunks.append(f"{block.list_marker} {block.text}".strip())
                else:
                    chunks.append(block.text)
            chunks.append("")
        path.write_text("\n\n".join(chunks).strip() + "\n", encoding="utf-8")
        return path


class MarkdownWriter(DocumentWriter):
    name = "md"
    extension = ".md"
    description = "마크다운"

    def write(self, document: Document, path: Path, options: ConvertOptions) -> Path:
        lines: list[str] = []
        if document.title:
            lines += [f"# {document.title}", ""]

        in_list = False
        for page in document.pages:
            for block in page.blocks:
                if block.is_empty():
                    continue
                # 목록이 끝나면 빈 줄을 넣어 다음 문단과 떼어 놓는다.
                if in_list and block.kind is not BlockKind.LIST_ITEM:
                    lines.append("")
                in_list = block.kind is BlockKind.LIST_ITEM
                if block.kind is BlockKind.HEADING:
                    level = min(6, max(1, block.level + 1))
                    lines += ["#" * level + " " + block.text, ""]
                elif block.kind is BlockKind.LIST_ITEM:
                    indent = "  " * block.level
                    marker = "1." if block.ordered else "-"
                    lines.append(f"{indent}{marker} {block.text}")
                else:
                    lines += [block.text, ""]
            if lines and lines[-1] != "":
                lines.append("")
            if options.page_break and page is not document.pages[-1]:
                lines += ["---", ""]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

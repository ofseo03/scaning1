// 일반 텍스트와 마크다운 출력.

const enc = new TextEncoder();

export function buildText(doc) {
  const chunks = [];
  for (const page of doc.pages) {
    for (const block of page.blocks) {
      if (!block.text || !block.text.trim()) continue;
      chunks.push(block.kind === 'list_item'
        ? `${block.listMarker} ${block.text}`.trim()
        : block.text);
    }
    chunks.push('');
  }
  return enc.encode(chunks.join('\n\n').trim() + '\n');
}

export function buildMarkdown(doc, options = {}) {
  const lines = [];
  if (doc.title) lines.push(`# ${doc.title}`, '');

  let inList = false;
  doc.pages.forEach((page, index) => {
    for (const block of page.blocks) {
      if (!block.text || !block.text.trim()) continue;
      // 목록이 끝나면 빈 줄을 넣어 다음 문단과 떼어 놓는다.
      if (inList && block.kind !== 'list_item') lines.push('');
      inList = block.kind === 'list_item';

      if (block.kind === 'heading') {
        lines.push('#'.repeat(Math.min(6, Math.max(1, block.level + 1))) + ' ' + block.text, '');
      } else if (block.kind === 'list_item') {
        lines.push('  '.repeat(block.level || 0) + (block.ordered ? '1.' : '-') + ' ' + block.text);
      } else {
        lines.push(block.text, '');
      }
    }
    if (lines.length && lines[lines.length - 1] !== '') lines.push('');
    if (options.pageBreak !== false && index < doc.pages.length - 1) lines.push('---', '');
  });
  return enc.encode(lines.join('\n').replace(/\s+$/, '') + '\n');
}

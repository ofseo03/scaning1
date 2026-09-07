// 브라우저에서 ZIP 파일을 만든다. .docx 와 .hwpx 가 모두 ZIP 이라 이 위에 얹는다.
//
// 외부 라이브러리를 쓰지 않는다. 압축은 브라우저에 이미 있는
// CompressionStream('deflate-raw') 을 쓴다(Chrome 80+, Safari 16.4+, Firefox 113+).
// .hwpx 는 mimetype 항목이 맨 앞에 무압축으로 들어가야 해서 저장(STORED) 방식도 함께 지원한다.

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const utf8 = new TextEncoder();

function toBytes(data) {
  if (typeof data === 'string') return utf8.encode(data);
  if (data instanceof Uint8Array) return data;
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  throw new TypeError('ZIP 항목은 문자열이나 바이트여야 합니다.');
}

async function deflateRaw(bytes) {
  if (typeof CompressionStream === 'undefined') return null;  // 압축 없이 저장한다
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** DOS 형식 날짜·시각(2초 단위). */
function dosDateTime(date) {
  const year = Math.max(1980, date.getFullYear());
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1),
    date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
  };
}

class ByteWriter {
  constructor() {
    this.chunks = [];
    this.length = 0;
  }
  push(bytes) {
    this.chunks.push(bytes);
    this.length += bytes.length;
  }
  u16(value) {
    const b = new Uint8Array(2);
    new DataView(b.buffer).setUint16(0, value, true);
    this.push(b);
  }
  u32(value) {
    const b = new Uint8Array(4);
    new DataView(b.buffer).setUint32(0, value >>> 0, true);
    this.push(b);
  }
  concat() {
    const out = new Uint8Array(this.length);
    let at = 0;
    for (const chunk of this.chunks) {
      out.set(chunk, at);
      at += chunk.length;
    }
    return out;
  }
}

/**
 * 항목 목록으로 ZIP 바이트를 만든다.
 * entries: [{ name, data, store }]  — store 가 참이면 압축하지 않는다.
 */
export async function makeZip(entries, { date = new Date() } = {}) {
  const { time, date: dosDate } = dosDateTime(date);
  const out = new ByteWriter();
  const central = [];

  for (const entry of entries) {
    const nameBytes = utf8.encode(entry.name);
    const raw = toBytes(entry.data);
    const sum = crc32(raw);

    let body = raw;
    let method = 0;                       // 0 = 저장
    if (!entry.store) {
      const packed = await deflateRaw(raw);
      // 압축해서 오히려 커지면 그냥 저장한다.
      if (packed && packed.length < raw.length) {
        body = packed;
        method = 8;                       // 8 = deflate
      }
    }

    const offset = out.length;
    out.u32(0x04034b50);                  // 로컬 파일 헤더
    out.u16(20);                          // 필요한 버전
    out.u16(0x0800);                      // 파일 이름은 UTF-8
    out.u16(method);
    out.u16(time);
    out.u16(dosDate);
    out.u32(sum);
    out.u32(body.length);
    out.u32(raw.length);
    out.u16(nameBytes.length);
    out.u16(0);                           // 여분 필드 없음
    out.push(nameBytes);
    out.push(body);

    central.push({ nameBytes, method, sum, packed: body.length, raw: raw.length, offset });
  }

  const centralStart = out.length;
  for (const item of central) {
    out.u32(0x02014b50);                  // 중앙 디렉터리 헤더
    out.u16(20);                          // 만든 버전
    out.u16(20);                          // 필요한 버전
    out.u16(0x0800);
    out.u16(item.method);
    out.u16(time);
    out.u16(dosDate);
    out.u32(item.sum);
    out.u32(item.packed);
    out.u32(item.raw);
    out.u16(item.nameBytes.length);
    out.u16(0);                           // 여분
    out.u16(0);                           // 주석
    out.u16(0);                           // 디스크 번호
    out.u16(0);                           // 내부 속성
    out.u32(0);                           // 외부 속성
    out.u32(item.offset);
    out.push(item.nameBytes);
  }

  const centralSize = out.length - centralStart;
  out.u32(0x06054b50);                    // 끝 기록
  out.u16(0);
  out.u16(0);
  out.u16(central.length);
  out.u16(central.length);
  out.u32(centralSize);
  out.u32(centralStart);
  out.u16(0);

  return out.concat();
}

/** XML 특수문자를 escape 하고 XML 1.0 이 허용하지 않는 제어문자를 걷어낸다. */
export function xmlEscape(text) {
  let clean = '';
  for (const ch of String(text ?? '')) {
    const code = ch.codePointAt(0);
    const ok = ch === '\t' || ch === '\n' || ch === '\r'
      || (code >= 0x20 && code <= 0xd7ff) || (code >= 0xe000 && code <= 0xfffd)
      || code >= 0x10000;
    if (ok) clean += ch;
  }
  return clean
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

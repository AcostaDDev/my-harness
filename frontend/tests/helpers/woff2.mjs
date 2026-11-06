// Offline reader of WOFF2 table data (brotli via node:zlib) for the font tests: the table directory, the cmap
// (formats 4 and 12) and the name table. Test-only; nothing is installed or fetched.
import { brotliDecompressSync } from 'node:zlib';
const TAGS = ['cmap','head','hhea','hmtx','maxp','name','OS/2','post','cvt ','fpgm','glyf','loca','prep','CFF ','VORG','EBDT','EBLC','gasp','hdmx','kern','LTSH','PCLT','VDMX','vhea','vmtx','BASE','GDEF','GPOS','GSUB','EBSC','JSTF','MATH','CBDT','CBLC','COLR','CPAL','SVG ','sbix','acnt','avar','bdat','bloc','bsln','cvar','fdsc','feat','fmtx','fvar','gvar','hsty','just','lcar','mort','morx','opbd','prop','trak','Zapf','Silf','Glat','Gloc','Feat','Sill'];
export function tables(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  if (dv.getUint32(0) !== 0x774f4632) throw new Error('not woff2');
  const numTables = dv.getUint16(12); const compLen = dv.getUint32(20);
  let off = 48; const dir = [];
  const b128 = () => { let v = 0; for (let i = 0; i < 5; i++) { const b = buf[off++]; v = (v << 7) | (b & 0x7f); if (!(b & 0x80)) return v >>> 0; } throw new Error('b128'); };
  for (let i = 0; i < numTables; i++) {
    const flags = buf[off++]; let tag = TAGS[flags & 0x3f];
    if ((flags & 0x3f) === 0x3f) { tag = String.fromCharCode(...buf.slice(off, off + 4)); off += 4; }
    const xf = (flags >> 6) & 3; const origLength = b128();
    let length = origLength; const transformed = (tag === 'glyf' || tag === 'loca') ? xf === 0 : xf !== 0;
    if (transformed) length = b128();
    dir.push({ tag, length, transformed });
  }
  const data = brotliDecompressSync(buf.subarray(off, off + compLen));
  let p = 0; const out = {};
  for (const t of dir) { out[t.tag] = { bytes: data.subarray(p, p + t.length), transformed: t.transformed }; p += t.length; }
  return out;
}
export function cmap(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const n = dv.getUint16(2); const cps = new Set();
  for (let i = 0; i < n; i++) {
    const pid = dv.getUint16(4 + i * 8), eid = dv.getUint16(6 + i * 8), o = dv.getUint32(8 + i * 8);
    const fmt = dv.getUint16(o);
    if (fmt === 4 && pid === 3 && (eid === 1 || eid === 0)) {
      const seg = dv.getUint16(o + 6) / 2; const ends = o + 14, starts = ends + seg * 2 + 2, deltas = starts + seg * 2, ros = deltas + seg * 2;
      for (let s = 0; s < seg; s++) {
        const end = dv.getUint16(ends + s * 2), start = dv.getUint16(starts + s * 2), delta = dv.getInt16(deltas + s * 2), ro = dv.getUint16(ros + s * 2);
        for (let c = start; c <= end && c !== 0xffff; c++) {
          let g; if (!ro) g = (c + delta) & 0xffff; else { const gi = dv.getUint16(ros + s * 2 + ro + (c - start) * 2); g = gi ? (gi + delta) & 0xffff : 0; }
          if (g) cps.add(c);
        }
      }
    } else if (fmt === 12) {
      const groups = dv.getUint32(o + 12);
      for (let g = 0; g < groups; g++) { const s = dv.getUint32(o + 16 + g * 12), e = dv.getUint32(o + 20 + g * 12), gid = dv.getUint32(o + 24 + g * 12); for (let c = s; c <= e; c++) if (gid + c - s) cps.add(c); }
    }
  }
  return cps;
}
export function names(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = dv.getUint16(2), so = dv.getUint16(4); const out = {};
  for (let i = 0; i < count; i++) {
    const r = 6 + i * 12; const pid = dv.getUint16(r), id = dv.getUint16(r + 6), len = dv.getUint16(r + 8), o = dv.getUint16(r + 10);
    if (pid !== 3) continue; let s = ''; for (let k = 0; k < len; k += 2) s += String.fromCharCode(dv.getUint16(so + o + k)); out[id] = s;
  }
  return out;
}

// Strict ISO-BMFF traversal for the proven AVC fMP4 format, not a byte search.
function boxes(view, start, end) {
  const result = [];
  for (let offset = start; offset < end;) {
    if (result.length >= 256 || end - offset < 8) throw new Error("invalid MP4 boxes");
    const small = view.getUint32(offset);
    const kind = String.fromCharCode(...new Uint8Array(view.buffer, view.byteOffset + offset + 4, 4));
    let header = 8, size = small;
    if (small === 1) {
      if (end - offset < 16) throw new Error("truncated MP4 size");
      const large = view.getBigUint64(offset + 8);
      if (large > BigInt(end - offset)) throw new Error("invalid MP4 size");
      header = 16; size = Number(large);
    }
    if (size < header || size > end - offset) throw new Error("invalid MP4 size");
    result.push({ kind, start: offset + header, end: offset + size });
    offset += size;
  }
  return result;
}
function one(view, parent, kind, skip = 0) {
  if (parent.start + skip > parent.end) throw new Error("invalid MP4 parent");
  const matches = boxes(view, parent.start + skip, parent.end).filter(b => b.kind === kind);
  if (matches.length !== 1) throw new Error("missing or duplicate MP4 box");
  return matches[0];
}
export function avcMime(init) {
  if (!(init instanceof Uint8Array) || init.length > 128 * 1024) throw new Error("invalid init");
  const v = new DataView(init.buffer, init.byteOffset, init.byteLength);
  const root = { start: 0, end: init.length };
  const top = boxes(v, 0, init.length);
  if (top.length !== 2 || top[0].kind !== "ftyp" || top[1].kind !== "moov") throw new Error("invalid MP4 init");
  let item = one(v, root, "moov");
  // The physical format is a single video-only track.
  for (const type of ["trak", "mdia", "minf", "stbl", "stsd"]) item = one(v, item, type);
  if (item.end - item.start < 8 || v.getUint32(item.start + 4) !== 1) throw new Error("invalid sample descriptions");
  const entries = boxes(v, item.start + 8, item.end);
  if (entries.length !== 1 || entries[0].kind !== "avc1") throw new Error("unsupported sample entry");
  const avcc = one(v, entries[0], "avcC", 78);
  if (avcc.end - avcc.start < 7 || v.getUint8(avcc.start) !== 1) throw new Error("invalid AVC config");
  const code = [1, 2, 3].map(i => v.getUint8(avcc.start + i).toString(16).padStart(2, "0")).join("");
  return 'video/mp4; codecs="avc1.' + code + '"';
}

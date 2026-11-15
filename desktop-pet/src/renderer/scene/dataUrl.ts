// The glb is bundled as a data: URL (Vite `?inline`) because the packaged app loads its page
// from file://, where fetch() is not allowed. Decoding it ourselves needs no network or CSP.

export function dataUrlToArrayBuffer(dataUrl: string): ArrayBuffer {
  const comma = dataUrl.indexOf(',');
  if (!dataUrl.startsWith('data:') || comma < 0) throw new Error('not a data: URL');
  const header = dataUrl.slice(0, comma);
  const payload = dataUrl.slice(comma + 1);
  if (!header.endsWith(';base64')) {
    return new TextEncoder().encode(decodeURIComponent(payload)).buffer as ArrayBuffer;
  }
  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

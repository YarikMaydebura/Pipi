// `audio_b64` (base64 of a WAV file) → bytes for Web Audio's decodeAudioData.

export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64); // throws on invalid base64 (caller falls back to captions only)
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

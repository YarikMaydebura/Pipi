// crypto.randomUUID() only exists in secure contexts (https:// or localhost). The panel is
// opened over plain http://<laptop-ip>:8766 from a second laptop or phone, where it is missing,
// and makeWozCommand() from @pipi/shared relies on it. crypto.getRandomValues() works
// everywhere, so we build a standard v4 UUID from it.

type Bytes = Uint8Array<ArrayBuffer>;
type RandomFill = (bytes: Bytes) => Bytes;

const defaultFill: RandomFill = (bytes) => crypto.getRandomValues(bytes);

/** RFC 4122 version-4 UUID, e.g. "3b241101-e2bb-4255-8caf-4136c566a962". */
export function uuidV4(fill: RandomFill = defaultFill): string {
  const bytes = fill(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40; // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Give crypto.randomUUID a fallback when the page is not a secure context. */
export function ensureRandomUUID(target: Crypto = crypto): void {
  if (typeof target.randomUUID === 'function') return;
  Object.defineProperty(target, 'randomUUID', {
    value: () => uuidV4((bytes) => target.getRandomValues(bytes)),
    configurable: true,
  });
}

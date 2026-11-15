import { describe, expect, it } from 'vitest';
import { ensureRandomUUID, uuidV4 } from './uuid';

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('uuidV4', () => {
  it('produces RFC 4122 version-4 ids', () => {
    expect(uuidV4()).toMatch(V4);
    expect(uuidV4((bytes) => bytes.fill(255))).toMatch(V4);
    expect(uuidV4((bytes) => bytes.fill(0))).toBe('00000000-0000-4000-8000-000000000000');
  });

  it('installs randomUUID only when it is missing (plain http on the LAN)', () => {
    const insecure = { getRandomValues: crypto.getRandomValues.bind(crypto) } as unknown as Crypto;
    ensureRandomUUID(insecure);
    expect(insecure.randomUUID()).toMatch(V4);
    const native = crypto.randomUUID;
    ensureRandomUUID(crypto);
    expect(crypto.randomUUID).toBe(native);
  });
});

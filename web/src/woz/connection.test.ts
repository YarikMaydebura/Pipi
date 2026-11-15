import { describe, expect, it } from 'vitest';
import { tokenFromSearch, wozSocketUrl } from './connection';

describe('wozSocketUrl', () => {
  it('uses the page host and passes the token on', () => {
    const url = wozSocketUrl({
      protocol: 'http:',
      host: '192.168.1.5:8766',
      search: '?token=a b&x=1',
    });
    expect(url).toBe('ws://192.168.1.5:8766/ws/woz?token=a%20b');
  });

  it('uses wss on https and omits a missing token', () => {
    expect(wozSocketUrl({ protocol: 'https:', host: 'pipi.local', search: '' })).toBe(
      'wss://pipi.local/ws/woz',
    );
  });

  it('treats an empty token as missing', () => {
    expect(tokenFromSearch('?token=')).toBeNull();
    expect(tokenFromSearch('?token=%20abc%20')).toBe('abc');
  });
});

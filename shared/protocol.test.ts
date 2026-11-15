import { describe, expect, it } from 'vitest';
import examples from './fixtures/protocol_examples.json';
import {
  BodyToBrain,
  BrainToBody,
  BrainToWoz,
  WozCommand,
  makeBodyMessage,
  makeWozCommand,
  newMessageId,
  parseBrainMessage,
  parseBrainToWozMessage,
} from './protocol';

// The same fixture file is validated by brain/tests/test_protocol.py (drift guard).

describe('protocol fixtures (shared with the Python brain)', () => {
  it.each(examples.brain_to_body)('accepts brain->body $type', (example) => {
    expect(BrainToBody.safeParse(example).success).toBe(true);
  });

  it.each(examples.body_to_brain)('accepts body->brain $type', (example) => {
    expect(BodyToBrain.safeParse(example).success).toBe(true);
  });

  it.each(examples.invalid_brain_to_body)('rejects invalid brain->body $type', (example) => {
    expect(BrainToBody.safeParse(example).success).toBe(false);
  });

  it.each(examples.invalid_body_to_brain)('rejects invalid body->brain $type', (example) => {
    expect(BodyToBrain.safeParse(example).success).toBe(false);
  });

  it.each(examples.woz_to_brain)('accepts woz->brain $command', (example) => {
    expect(WozCommand.safeParse(example).success).toBe(true);
  });

  it.each(examples.brain_to_woz)('accepts brain->woz $type', (example) => {
    expect(BrainToWoz.safeParse(example).success).toBe(true);
  });

  it.each(examples.invalid_woz_to_brain)('rejects invalid woz->brain $id', (example) => {
    expect(WozCommand.safeParse(example).success).toBe(false);
  });

  it.each(examples.invalid_brain_to_woz)('rejects invalid brain->woz $id', (example) => {
    expect(BrainToWoz.safeParse(example).success).toBe(false);
  });

  it('covers every message type at least once', () => {
    const brainTypes = new Set(examples.brain_to_body.map((m) => m.type));
    const bodyTypes = new Set(examples.body_to_brain.map((m) => m.type));
    const wozTypes = new Set(examples.brain_to_woz.map((m) => m.type));
    const allBrainTypes = BrainToBody.options.map((o) => o.shape.type.value);
    const allBodyTypes = BodyToBrain.options.map((o) => o.shape.type.value);
    const allWozTypes = BrainToWoz.options.map((o) => o.shape.type.value);
    expect([...brainTypes].sort()).toEqual([...allBrainTypes].sort());
    expect([...bodyTypes].sort()).toEqual([...allBodyTypes].sort());
    expect([...wozTypes].sort()).toEqual([...allWozTypes].sort());
  });
});

describe('newMessageId', () => {
  const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  it('uses crypto.randomUUID when the page is a secure context', () => {
    expect(newMessageId()).toMatch(V4);
  });

  it('still makes a valid v4 id without randomUUID (plain http on the LAN)', () => {
    const insecure = { getRandomValues: crypto.getRandomValues.bind(crypto) };
    const a = newMessageId(insecure);
    const b = newMessageId(insecure);
    expect(a).toMatch(V4);
    expect(a).not.toBe(b);
  });
});

describe('WoZ helpers', () => {
  it('makeWozCommand adds id, timestamp and default args', () => {
    const command = makeWozCommand({ command: 'pause', reason: 'timing' });
    expect(command.type).toBe('woz_command');
    expect(command.id.length).toBeGreaterThan(0);
    expect(command.args).toEqual({});
  });

  it('makeWozCommand rejects an unknown reason', () => {
    expect(() =>
      makeWozCommand({ command: 'pause', reason: 'bored' as unknown as 'timing' }),
    ).toThrow();
  });

  it('parseBrainToWozMessage never throws on garbage', () => {
    expect(parseBrainToWozMessage('{nope').ok).toBe(false);
    expect(parseBrainToWozMessage(JSON.stringify(examples.brain_to_woz[0])).ok).toBe(true);
  });
});

describe('parseBrainMessage', () => {
  it('returns the parsed message for valid JSON', () => {
    const raw = JSON.stringify(examples.brain_to_body[0]);
    const result = parseBrainMessage(raw);
    expect(result.ok).toBe(true);
  });

  it('applies the default expression when speak has none', () => {
    const result = parseBrainMessage(JSON.stringify({ type: 'speak', id: 'a', ts: 1, text: 'hi' }));
    expect(result.ok && result.message.type === 'speak' && result.message.expression).toBe('idle');
  });

  it('returns an error instead of throwing for broken JSON', () => {
    const result = parseBrainMessage('{not json');
    expect(result).toEqual({ ok: false, error: 'message is not valid JSON' });
  });

  it('returns an error for a schema violation', () => {
    const result = parseBrainMessage(JSON.stringify({ type: 'eyes', id: 'a', ts: 1 }));
    expect(result.ok).toBe(false);
  });
});

describe('makeBodyMessage', () => {
  it('adds an id and timestamp', () => {
    const msg = makeBodyMessage({ type: 'hello', body: 'desktop_pet', version: '0.1.0' });
    expect(msg.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(msg.ts).toBeGreaterThan(0);
  });
});

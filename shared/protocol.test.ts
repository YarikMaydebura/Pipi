import { describe, expect, it } from 'vitest';
import examples from './fixtures/protocol_examples.json';
import { BodyToBrain, BrainToBody, makeBodyMessage, parseBrainMessage } from './protocol';

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

  it('covers every message type at least once', () => {
    const brainTypes = new Set(examples.brain_to_body.map((m) => m.type));
    const bodyTypes = new Set(examples.body_to_brain.map((m) => m.type));
    const allBrainTypes = BrainToBody.options.map((o) => o.shape.type.value);
    const allBodyTypes = BodyToBrain.options.map((o) => o.shape.type.value);
    expect([...brainTypes].sort()).toEqual([...allBrainTypes].sort());
    expect([...bodyTypes].sort()).toEqual([...allBodyTypes].sort());
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

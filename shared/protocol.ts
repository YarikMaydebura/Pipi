/**
 * WebSocket message protocol between the brain and the bodies (desktop pet, fake robot).
 *
 * Mirrors brain/pipi_brain/protocol.py EXACTLY. Change both in the same step.
 * shared/fixtures/protocol_examples.json is validated by the tests on both sides, so a change
 * made on only one side fails a test.
 *
 * Every message is JSON: {"type": "...", "id": "<uuid>", "ts": <epoch_ms>, ...payload}.
 * Unknown fields are rejected (strict objects), matching pydantic's extra="forbid".
 */
import { z } from 'zod';

export const PROTOCOL_VERSION = '0.1.0';

export const EyeState = z.enum([
  'idle',
  'blink',
  'listening',
  'thinking',
  'happy',
  'sad',
  'surprised',
  'determined',
  'sleepy',
  'off',
  'countdown',
  'signal_go',
]);
export type EyeState = z.infer<typeof EyeState>;

export const Expression = z.enum([
  'idle',
  'happy',
  'surprised',
  'thinking',
  'sad',
  'sleepy',
  'determined',
]);
export type Expression = z.infer<typeof Expression>;

export const BodyName = z.enum(['desktop_pet', 'fake_robot']);
export type BodyName = z.infer<typeof BodyName>;

const envelope = {
  id: z.string().min(1),
  ts: z.number().int().nonnegative(),
};

// --- Brain -> body ---------------------------------------------------------------------------

export const Activate = z.strictObject({
  type: z.literal('activate'),
  ...envelope,
  entrance: z.enum(['jump_in', 'wake_up', 'fade_in']),
});

export const Deactivate = z.strictObject({
  type: z.literal('deactivate'),
  ...envelope,
  exit: z.enum(['jump_out', 'sleep', 'fade_out']),
});

export const Speak = z.strictObject({
  type: z.literal('speak'),
  ...envelope,
  text: z.string(),
  audio_b64: z.string().nullish(), // tts-1 audio; absent = captions only
  expression: Expression.default('idle'),
});

export const Eyes = z.strictObject({
  type: z.literal('eyes'),
  ...envelope,
  state: EyeState,
});

export const Motion = z.strictObject({
  type: z.literal('motion'),
  ...envelope,
  name: z.string().min(1), // a named motion from config/motions.yaml
});

export const Caption = z.strictObject({
  type: z.literal('caption'),
  ...envelope,
  text: z.string().nullable(), // null hides the caption
});

export const BrainToBody = z.discriminatedUnion('type', [
  Activate,
  Deactivate,
  Speak,
  Eyes,
  Motion,
  Caption,
]);
export type BrainToBody = z.infer<typeof BrainToBody>;

// --- Body -> brain ---------------------------------------------------------------------------

export const Hello = z.strictObject({
  type: z.literal('hello'),
  ...envelope,
  body: BodyName,
  version: z.string().min(1),
});

export const Ack = z.strictObject({
  type: z.literal('ack'),
  ...envelope,
  ref_id: z.string().min(1),
  ok: z.boolean(),
  error: z.string().nullish(),
});

export const SpeechDone = z.strictObject({
  type: z.literal('speech_done'),
  ...envelope,
  ref_id: z.string().min(1),
  duration_ms: z.number().int().nonnegative(),
});

export const UserClick = z.strictObject({
  type: z.literal('user_click'),
  ...envelope,
  target: z.string().min(1),
});

export const BodyToBrain = z.discriminatedUnion('type', [Hello, Ack, SpeechDone, UserClick]);
export type BodyToBrain = z.infer<typeof BodyToBrain>;

// --- Helpers ---------------------------------------------------------------------------------

/** Distributes Omit over a union, so each message type keeps its own payload fields. */
export type WithoutEnvelope<T> = T extends unknown ? Omit<T, 'id' | 'ts'> : never;

/** Build an outgoing body -> brain message: adds a fresh id and timestamp, then validates. */
export function makeBodyMessage(payload: WithoutEnvelope<BodyToBrain>): BodyToBrain {
  return BodyToBrain.parse({ ...payload, id: crypto.randomUUID(), ts: Date.now() });
}

export type ParseResult<T> = { ok: true; message: T } | { ok: false; error: string };

/** Validate a raw WebSocket frame from the brain. Never throws. */
export function parseBrainMessage(raw: string): ParseResult<BrainToBody> {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return { ok: false, error: 'message is not valid JSON' };
  }
  const result = BrainToBody.safeParse(data);
  return result.success
    ? { ok: true, message: result.data }
    : { ok: false, error: z.prettifyError(result.error) };
}

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

export const RobotSide = z.enum(['left', 'right']);
export type RobotSide = z.infer<typeof RobotSide>;

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
  // base64 of a complete WAV file (16-bit PCM mono, 24 kHz from the TTS model);
  // absent = captions only
  audio_b64: z.string().nullish(),
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

/** Sent once right after `hello`: settings the body needs (e.g. where the robot stands). */
export const BodyConfig = z.strictObject({
  type: z.literal('body_config'),
  ...envelope,
  robot_side: RobotSide, // screen edge facing the robot: Pipi jumps off / lands on this side
});

/** Calm mode on/off: during FOCUS the pet stays quiet (no fidgets, tiny reactions only). */
export const Calm = z.strictObject({
  type: z.literal('calm'),
  ...envelope,
  on: z.boolean(),
});

export const BrainToBody = z.discriminatedUnion('type', [
  Activate,
  Deactivate,
  Speak,
  Eyes,
  Motion,
  Caption,
  BodyConfig,
  Calm,
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

// --- WoZ <-> brain (experimenter panel, docs/INTERACTION_FLOW.md §4) ------------------------

export const Phase = z.enum([
  'SETUP',
  'PERSONA_PICK',
  'GREETING',
  'FOCUS',
  'MIGRATE_OUT',
  'ROBOT_WAKE',
  'CHAT',
  'GAME_CROCODILE',
  'GAME_MENU',
  'GAME_CHOSEN',
  'ROBOT_GOODBYE',
  'MIGRATE_IN',
  'RETURN',
  'END',
]);
export type Phase = z.infer<typeof Phase>;

export const WozCommandName = z.enum([
  'start_session',
  'next_phase',
  'goto_phase',
  'extend_focus',
  'trigger_migration_out',
  'trigger_migration_in',
  'say',
  'say_text',
  'start_game',
  'end_game',
  'switch_robot_body',
  'set_eyes',
  'play_motion',
  'pause',
  'resume',
  'emergency_stop',
  'end_session',
]);
export type WozCommandName = z.infer<typeof WozCommandName>;

export const WozReason = z.enum([
  'technical_failure',
  'participant_confused',
  'timing',
  'participant_request',
  'demo',
  'other',
]);
export type WozReason = z.infer<typeof WozReason>;

export const ActiveBody = z.enum(['desktop_pet', 'fake_robot', 'alpha_mini']);
export type ActiveBody = z.infer<typeof ActiveBody>;

/** Every experimenter action, always with a reason (logged for the study). */
export const WozCommand = z.strictObject({
  type: z.literal('woz_command'),
  ...envelope,
  command: WozCommandName,
  // command arguments, e.g. {phase: "CHAT"}, {seconds: 60}; validated per command by the brain
  args: z.record(z.string(), z.union([z.string(), z.number(), z.boolean()])).default({}),
  reason: WozReason,
  note: z.string().nullish(), // free text, required by the panel when reason == "other"
});
export type WozCommand = z.infer<typeof WozCommand>;

const TimerInfo = z.strictObject({
  name: z.string().min(1), // e.g. "focus", "break"
  remaining_s: z.number().nonnegative(),
  total_s: z.number().nonnegative(),
});

const BodyHealth = z.strictObject({
  connected: z.boolean(),
  last_error: z.string().nullish(),
});

const TurnLatencies = z.strictObject({
  stt_ms: z.number().int().nonnegative().nullish(),
  llm_ms: z.number().int().nonnegative().nullish(),
  tts_ms: z.number().int().nonnegative().nullish(),
  total_ms: z.number().int().nonnegative().nullish(),
});

/** Sent to the WoZ panel on every change (and as the first message after it connects). */
export const StateUpdate = z.strictObject({
  type: z.literal('state_update'),
  ...envelope,
  phase: Phase,
  mode: z.enum(['dev', 'study', 'demo']),
  participant_id: z.string().nullish(),
  active_body: ActiveBody.nullish(),
  timer: TimerInfo.nullish(),
  paused: z.boolean().default(false),
  memory_summary: z.record(z.string(), z.string()).default({}),
  health: z.record(z.string(), BodyHealth).default({}), // body name -> health
});

export const Turn = z.strictObject({
  type: z.literal('turn'),
  ...envelope,
  speaker: z.enum(['user', 'pipi']),
  text: z.string(),
  latencies: TurnLatencies.nullish(),
});

export const Alert = z.strictObject({
  type: z.literal('alert'),
  ...envelope,
  level: z.enum(['info', 'warning', 'error']),
  message: z.string().min(1),
});

export const BrainToWoz = z.discriminatedUnion('type', [StateUpdate, Turn, Alert, Ack]);
export type BrainToWoz = z.infer<typeof BrainToWoz>;
export const WozToBrain = WozCommand;
export type WozToBrain = WozCommand;

// --- Helpers ---------------------------------------------------------------------------------

/** Distributes Omit over a union, so each message type keeps its own payload fields. */
export type WithoutEnvelope<T> = T extends unknown ? Omit<T, 'id' | 'ts'> : never;

/**
 * A fresh message id (UUID v4). crypto.randomUUID() only exists in secure contexts (https or
 * localhost); the fake robot and the WoZ panel are also opened over plain http://<laptop-ip>
 * on the LAN, where only crypto.getRandomValues() is available.
 */
export function newMessageId(source: Pick<Crypto, 'getRandomValues'> = crypto): string {
  const native = (source as Partial<Crypto>).randomUUID;
  if (typeof native === 'function') return native.call(source);
  const bytes = source.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40; // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Build an outgoing body -> brain message: adds a fresh id and timestamp, then validates. */
export function makeBodyMessage(payload: WithoutEnvelope<BodyToBrain>): BodyToBrain {
  return BodyToBrain.parse({ ...payload, id: newMessageId(), ts: Date.now() });
}

export type ParseResult<T> = { ok: true; message: T } | { ok: false; error: string };

function parseWith<T>(schema: z.ZodType<T>, raw: string): ParseResult<T> {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return { ok: false, error: 'message is not valid JSON' };
  }
  const result = schema.safeParse(data);
  return result.success
    ? { ok: true, message: result.data }
    : { ok: false, error: z.prettifyError(result.error) };
}

/** Validate a raw WebSocket frame from the brain (body channel). Never throws. */
export function parseBrainMessage(raw: string): ParseResult<BrainToBody> {
  return parseWith(BrainToBody, raw);
}

/** Validate a raw WebSocket frame from the brain on the WoZ channel. Never throws. */
export function parseBrainToWozMessage(raw: string): ParseResult<BrainToWoz> {
  return parseWith(BrainToWoz, raw);
}

/** Build an outgoing WoZ command: adds a fresh id and timestamp, then validates. */
export function makeWozCommand(
  payload: Omit<z.input<typeof WozCommand>, 'id' | 'ts' | 'type'>,
): WozCommand {
  return WozCommand.parse({
    ...payload,
    type: 'woz_command',
    id: newMessageId(),
    ts: Date.now(),
  });
}

// What every WoZ command needs from the experimenter, and the validation of the form
// (unit-tested in commands.test.ts). Argument keys are the contract with the brain's
// session controller: docs/SYSTEM_DESIGN.md §4.8 lists them.
import { EyeState, Phase, WozCommandName, WozReason } from '@pipi/shared';

export type CommandName = WozCommandName;
export type ReasonValue = WozReason;
export type ArgValue = string | number | boolean;

/** Games the brain can run now (M4); listed first in the start_game control. */
export const AVAILABLE_GAMES = ['crocodile_robot', 'quick_draw'] as const;
/** Games planned for a later milestone: still offered, marked "(later)"; the brain refuses them. */
export const LATER_GAMES = ['staring', 'rps_arms', 'crocodile_human'] as const;
export const GAMES = [...AVAILABLE_GAMES, ...LATER_GAMES] as const;

const GAME_NAMES: Readonly<Record<(typeof GAMES)[number], string>> = {
  crocodile_robot: 'Crocodile — robot acts, you guess',
  quick_draw: 'Quick-draw duel',
  staring: 'Staring contest',
  rps_arms: 'Arm rock-paper-scissors',
  crocodile_human: 'Crocodile — you act, robot guesses',
};

/** What the start_game control shows for each game id, e.g. "Staring contest (later)". */
export const GAME_LABELS: Readonly<Record<string, string>> = Object.fromEntries(
  GAMES.map((game) => [
    game,
    (LATER_GAMES as readonly string[]).includes(game)
      ? `${GAME_NAMES[game]} (later)`
      : GAME_NAMES[game],
  ]),
);

/** Fixed lines from config/lines.yaml (the brain decides which ids exist). */
export const LINE_SUGGESTIONS = [
  'opening',
  'stt_retry',
  'llm_fallback',
  'silence_reprompt',
  'goodbye',
] as const;

/**
 * Named motions from docs/GAMES.md §2 that the bodies know today (the body decides which ones
 * it can play: the pet refuses the game motions). play_motion suggests them; other names can
 * still be typed.
 */
export const SOCIAL_MOTIONS = [
  'wave',
  'signature_wave',
  'nod',
  'shake_head',
  'think',
  'excited',
  'happy',
  'celebrate',
  'sad',
  'shrug',
  'bow',
  'dance',
  'wake_up',
  'sleep',
] as const;
/** Crocodile acting loops (robot only): they repeat until the next motion or a stop. */
export const CROCODILE_MOTIONS = [
  'act_bird',
  'act_boxer',
  'act_swimmer',
  'act_dancer',
  'act_robot',
  'act_sleeping',
  'act_superhero',
  'act_drummer',
] as const;
/** Quick-draw duel (robot only): duel_ready holds until one of the others. */
export const DUEL_MOTIONS = ['duel_ready', 'duel_draw', 'duel_hit', 'duel_win'] as const;
export const STARE_MOTIONS = ['stare_ready', 'stare_lose'] as const;
export const RPS_MOTIONS = ['rps_shake', 'rps_rock', 'rps_paper', 'rps_scissors'] as const;
export const MOTION_SUGGESTIONS: readonly string[] = [
  ...SOCIAL_MOTIONS,
  ...CROCODILE_MOTIONS,
  ...DUEL_MOTIONS,
  ...STARE_MOTIONS,
  ...RPS_MOTIONS,
  'idle', // ends an acting loop without an emergency stop
];

export const MAX_EXTEND_S = 600;
export const MAX_TEXT_CHARS = 300; // brain: phases/woz_commands.py MAX_SAY_TEXT
export const MAX_NOTE_CHARS = 500;
/** Line ids and motion names (brain: NAME_PATTERN). */
export const NAME_PATTERN = /^[a-z0-9_]{1,64}$/;
/** Pseudonymous participant ids, same rule as the study logger. */
export const PARTICIPANT_PATTERN = /^[A-Za-z0-9_-]{1,32}$/;

interface FieldBase {
  readonly key: string;
  readonly label: string;
  /** Optional fields may stay empty; they are then left out of `args`. */
  readonly optional?: boolean;
}

export interface SelectField extends FieldBase {
  readonly kind: 'select';
  readonly options: readonly string[];
  /** Text shown for an option (default: the option made readable, "quick_draw" → "Quick draw"). */
  readonly optionLabels?: Readonly<Record<string, string>>;
}

export interface NumberField extends FieldBase {
  readonly kind: 'number';
  readonly min: number;
  readonly max: number;
}

export interface TextField extends FieldBase {
  readonly kind: 'text';
  readonly maxLength: number;
  readonly suggestions: readonly string[];
  readonly multiline: boolean;
  readonly pattern?: RegExp;
  readonly patternHint?: string;
}

/** A checkbox: checked sends `true`, unchecked leaves the key out. */
export interface ToggleField extends FieldBase {
  readonly kind: 'toggle';
}

export type ArgField = SelectField | NumberField | TextField | ToggleField;

export type CommandGroup = 'session' | 'flow' | 'speech' | 'games' | 'body';

export interface CommandSpec {
  readonly name: CommandName;
  readonly label: string;
  readonly group: CommandGroup;
  readonly hint: string;
  readonly fields: readonly ArgField[];
  /** Ask "tap again to confirm" before sending (destructive or flow-breaking). */
  readonly confirm: boolean;
}

const phaseField: SelectField = {
  key: 'phase',
  label: 'Phase',
  kind: 'select',
  options: Phase.options,
};

export const COMMAND_SPECS: readonly CommandSpec[] = [
  {
    name: 'start_session',
    label: 'Start session',
    group: 'session',
    hint: 'SETUP → PERSONA_PICK',
    fields: [
      {
        key: 'participant_id',
        label: 'Participant id check (optional, must match the brain)',
        kind: 'text',
        maxLength: 32,
        suggestions: [],
        multiline: false,
        pattern: PARTICIPANT_PATTERN,
        patternHint: 'letters, digits, _ or -, e.g. P01',
        optional: true,
      },
      {
        key: 'override',
        label: 'Start even if body health is not green (study mode)',
        kind: 'toggle',
        optional: true,
      },
    ],
    confirm: false,
  },
  {
    name: 'pause',
    label: 'Pause',
    group: 'session',
    hint: 'Freeze timers and listening',
    fields: [],
    confirm: false,
  },
  {
    name: 'resume',
    label: 'Resume',
    group: 'session',
    hint: 'Continue timers and listening',
    fields: [],
    confirm: false,
  },
  {
    name: 'end_session',
    label: 'End session',
    group: 'session',
    hint: 'Go to END and close the log',
    fields: [],
    confirm: true,
  },
  {
    name: 'emergency_stop',
    label: 'Emergency stop',
    group: 'session',
    hint: 'Stop all motion and audio now',
    fields: [],
    confirm: false,
  },
  {
    name: 'next_phase',
    label: 'Next phase',
    group: 'flow',
    hint: 'Force the next transition',
    fields: [],
    confirm: false,
  },
  {
    name: 'goto_phase',
    label: 'Go to phase…',
    group: 'flow',
    hint: 'Jump to any phase',
    fields: [phaseField],
    confirm: true,
  },
  {
    name: 'extend_focus',
    label: 'Extend focus…',
    group: 'flow',
    hint: 'Add seconds to the focus timer',
    fields: [{ key: 'seconds', label: 'Seconds', kind: 'number', min: 1, max: MAX_EXTEND_S }],
    confirm: false,
  },
  {
    name: 'trigger_migration_out',
    label: 'Migrate out',
    group: 'flow',
    hint: 'Pet → robot now',
    fields: [],
    confirm: false,
  },
  {
    name: 'trigger_migration_in',
    label: 'Migrate in',
    group: 'flow',
    hint: 'Robot → pet now',
    fields: [],
    confirm: false,
  },
  {
    name: 'say',
    label: 'Say line…',
    group: 'speech',
    hint: 'Speak a prepared line (lines.yaml id)',
    fields: [
      {
        key: 'line_id',
        label: 'Line id',
        kind: 'text',
        maxLength: 64,
        pattern: NAME_PATTERN,
        patternHint: 'lowercase letters, digits and _',
        suggestions: LINE_SUGGESTIONS,
        multiline: false,
      },
    ],
    confirm: false,
  },
  {
    name: 'say_text',
    label: 'Say text…',
    group: 'speech',
    hint: 'Pipi speaks this exact text',
    fields: [
      {
        key: 'text',
        label: 'Text',
        kind: 'text',
        maxLength: MAX_TEXT_CHARS,
        suggestions: [],
        multiline: true,
      },
    ],
    confirm: false,
  },
  {
    name: 'start_game',
    label: 'Start game…',
    group: 'games',
    hint: 'Start a game now (during the break)',
    fields: [
      { key: 'game', label: 'Game', kind: 'select', options: GAMES, optionLabels: GAME_LABELS },
    ],
    confirm: false,
  },
  {
    name: 'end_game',
    label: 'End game',
    group: 'games',
    hint: 'Finish the current game',
    fields: [],
    confirm: false,
  },
  {
    name: 'switch_robot_body',
    label: 'Switch robot…',
    group: 'body',
    hint: 'Swap the robot-side body (backup)',
    fields: [{ key: 'body', label: 'Robot body', kind: 'select', options: ['fake', 'real'] }],
    confirm: true,
  },
  {
    name: 'set_eyes',
    label: 'Set eyes…',
    group: 'body',
    hint: 'Eye state on the active body',
    fields: [{ key: 'state', label: 'Eye state', kind: 'select', options: EyeState.options }],
    confirm: false,
  },
  {
    name: 'play_motion',
    label: 'Play motion…',
    group: 'body',
    hint: 'Named motion on the active body (act_* and duel_* only on the robot)',
    fields: [
      {
        key: 'name',
        label: 'Motion',
        kind: 'text',
        maxLength: 64,
        pattern: NAME_PATTERN,
        patternHint: 'lowercase letters, digits and _',
        suggestions: MOTION_SUGGESTIONS,
        multiline: false,
      },
    ],
    confirm: false,
  },
];

export const GROUP_LABELS: Readonly<Record<CommandGroup, string>> = {
  session: 'Session',
  flow: 'Flow',
  speech: 'Speech',
  games: 'Games',
  body: 'Body',
};

export const REASONS: readonly { readonly value: ReasonValue; readonly label: string }[] = [
  { value: 'technical_failure', label: 'Technical failure' },
  { value: 'participant_confused', label: 'Participant confused / stuck' },
  { value: 'timing', label: 'Timing' },
  { value: 'participant_request', label: 'Participant request' },
  { value: 'demo', label: 'Demo' },
  { value: 'other', label: 'Other (note required)' },
];

/** The emergency stop never waits for a form; this note marks it in the log. */
export const EMERGENCY_NOTE = 'Emergency stop button';

export function specFor(name: CommandName): CommandSpec {
  const spec = COMMAND_SPECS.find((candidate) => candidate.name === name);
  if (!spec) throw new Error(`no spec for command ${name}`);
  return spec;
}

export interface CommandForm {
  readonly command: CommandName;
  readonly values: Readonly<Record<string, string>>;
  readonly reason: string; // '' = not chosen yet
  readonly note: string;
}

export interface CommandPayload {
  readonly command: CommandName;
  readonly args: Record<string, ArgValue>;
  readonly reason: ReasonValue;
  readonly note: string | null;
}

export type FormResult =
  | { readonly ok: true; readonly payload: CommandPayload }
  | { readonly ok: false; readonly errors: Readonly<Record<string, string>> };

function parseField(field: ArgField, raw: string): { value?: ArgValue; error?: string } {
  const text = raw.trim();
  if (field.kind === 'toggle') return text === 'true' ? { value: true } : {};
  if (text === '') return field.optional ? {} : { error: `${field.label} is required` };
  switch (field.kind) {
    case 'select':
      return field.options.includes(text)
        ? { value: text }
        : { error: `Choose a ${field.label.toLowerCase()}` };
    case 'number': {
      const value = Number(text);
      if (!Number.isInteger(value) || value < field.min || value > field.max) {
        return { error: `${field.label}: a whole number from ${field.min} to ${field.max}` };
      }
      return { value };
    }
    case 'text':
      if (text.length > field.maxLength) {
        return { error: `${field.label}: at most ${field.maxLength} characters` };
      }
      if (field.pattern && !field.pattern.test(text)) {
        return { error: `${field.label}: ${field.patternHint ?? 'invalid format'}` };
      }
      return { value: text };
  }
}

function isReason(value: string): value is ReasonValue {
  return (WozReason.options as readonly string[]).includes(value);
}

/** Check a filled-in form. Errors are keyed by field key, plus "reason" and "note". */
export function validateCommandForm(form: CommandForm): FormResult {
  const spec = specFor(form.command);
  const errors: Record<string, string> = {};
  const args: Record<string, ArgValue> = {};
  for (const field of spec.fields) {
    const result = parseField(field, form.values[field.key] ?? '');
    if (result.error !== undefined) errors[field.key] = result.error;
    else if (result.value !== undefined) args[field.key] = result.value;
  }
  const note = form.note.trim();
  if (!isReason(form.reason)) errors.reason = 'Choose a reason (required for every action)';
  else if (form.reason === 'other' && note === '') errors.note = 'Write a short note for "Other"';
  if (note.length > MAX_NOTE_CHARS) errors.note = `Note: at most ${MAX_NOTE_CHARS} characters`;
  if (Object.keys(errors).length > 0 || !isReason(form.reason)) return { ok: false, errors };
  return {
    ok: true,
    payload: { command: form.command, args, reason: form.reason, note: note === '' ? null : note },
  };
}

/** The emergency stop uses the chosen reason if there is a valid one, else "other" + a note. */
export function emergencyPayload(reason: string, note: string): CommandPayload {
  const trimmed = note.trim();
  const chosen: ReasonValue =
    isReason(reason) && (reason !== 'other' || trimmed !== '') ? reason : 'other';
  return { command: 'emergency_stop', args: {}, reason: chosen, note: trimmed || EMERGENCY_NOTE };
}

/** Short human summary of a command for the log list, e.g. "goto_phase phase=CHAT". */
export function describeCommand(
  command: CommandName,
  args: Readonly<Record<string, ArgValue>>,
): string {
  const parts = Object.entries(args).map(([key, value]) => `${key}=${String(value)}`);
  return [specFor(command).label.replace('…', ''), ...parts].join(' · ');
}

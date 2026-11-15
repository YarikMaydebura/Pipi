import { WozCommandName, makeWozCommand } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import {
  COMMAND_SPECS,
  EMERGENCY_NOTE,
  describeCommand,
  emergencyPayload,
  validateCommandForm,
  type CommandForm,
} from './commands';

function form(partial: Partial<CommandForm> & Pick<CommandForm, 'command'>): CommandForm {
  return { values: {}, reason: 'timing', note: '', ...partial };
}

describe('command specs', () => {
  it('cover every WoZ command exactly once', () => {
    const names = COMMAND_SPECS.map((spec) => spec.name);
    expect([...names].sort()).toEqual([...WozCommandName.options].sort());
  });

  it('ask for confirmation before end_session and goto_phase', () => {
    const confirmed = COMMAND_SPECS.filter((spec) => spec.confirm).map((spec) => spec.name);
    expect(confirmed).toContain('end_session');
    expect(confirmed).toContain('goto_phase');
    expect(confirmed).not.toContain('emergency_stop');
  });
});

describe('validateCommandForm', () => {
  it('builds a payload that the shared protocol accepts', () => {
    const result = validateCommandForm(form({ command: 'goto_phase', values: { phase: 'CHAT' } }));
    expect(result).toEqual({
      ok: true,
      payload: { command: 'goto_phase', args: { phase: 'CHAT' }, reason: 'timing', note: null },
    });
    if (result.ok) expect(makeWozCommand({ ...result.payload }).command).toBe('goto_phase');
  });

  it('requires a reason for every command', () => {
    const result = validateCommandForm(form({ command: 'pause', reason: '' }));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.reason).toMatch(/reason/i);
  });

  it('requires a note when the reason is other', () => {
    const missing = validateCommandForm(form({ command: 'pause', reason: 'other', note: '  ' }));
    expect(missing.ok).toBe(false);
    if (!missing.ok) expect(missing.errors.note).toBeDefined();
    const given = validateCommandForm(form({ command: 'pause', reason: 'other', note: ' alarm ' }));
    expect(given.ok && given.payload.note).toBe('alarm');
  });

  it('validates arguments per field type', () => {
    const cases: [CommandForm, string][] = [
      [form({ command: 'goto_phase', values: { phase: 'NAP' } }), 'phase'],
      [form({ command: 'extend_focus', values: { seconds: '0' } }), 'seconds'],
      [form({ command: 'extend_focus', values: { seconds: '1.5' } }), 'seconds'],
      [form({ command: 'say_text', values: { text: '   ' } }), 'text'],
      [form({ command: 'say_text', values: { text: 'x'.repeat(301) } }), 'text'],
      [form({ command: 'set_eyes', values: { state: 'angry' } }), 'state'],
      [form({ command: 'switch_robot_body', values: {} }), 'body'],
    ];
    for (const [input, key] of cases) {
      const result = validateCommandForm(input);
      expect(result.ok, `${input.command} ${JSON.stringify(input.values)}`).toBe(false);
      if (!result.ok) expect(result.errors[key]).toBeDefined();
    }
  });

  it('converts numbers and trims text', () => {
    const extend = validateCommandForm(
      form({ command: 'extend_focus', values: { seconds: ' 60 ' } }),
    );
    expect(extend.ok && extend.payload.args).toEqual({ seconds: 60 });
    const say = validateCommandForm(form({ command: 'say_text', values: { text: ' Hi! ' } }));
    expect(say.ok && say.payload.args).toEqual({ text: 'Hi!' });
  });
});

describe('emergencyPayload', () => {
  it('uses the chosen reason when valid', () => {
    expect(emergencyPayload('technical_failure', '')).toEqual({
      command: 'emergency_stop',
      args: {},
      reason: 'technical_failure',
      note: EMERGENCY_NOTE,
    });
  });

  it('falls back to other + note when no usable reason is chosen', () => {
    expect(emergencyPayload('', '').reason).toBe('other');
    expect(emergencyPayload('other', '').note).toBe(EMERGENCY_NOTE);
    expect(emergencyPayload('other', 'robot fell').note).toBe('robot fell');
  });
});

it('describes commands for the log', () => {
  expect(describeCommand('goto_phase', { phase: 'CHAT' })).toBe('Go to phase · phase=CHAT');
});

describe('brain contract (phases/woz_commands.py)', () => {
  it('keeps optional start_session fields out of args unless filled in', () => {
    const plain = validateCommandForm(form({ command: 'start_session' }));
    expect(plain.ok && plain.payload.args).toEqual({});
    const full = validateCommandForm(
      form({ command: 'start_session', values: { participant_id: 'P07', override: 'true' } }),
    );
    expect(full.ok && full.payload.args).toEqual({ participant_id: 'P07', override: true });
    const bad = validateCommandForm(
      form({ command: 'start_session', values: { participant_id: 'Jan Smit' } }),
    );
    expect(bad.ok).toBe(false);
  });

  it('accepts only name-like line ids and motion names, and 300-char texts', () => {
    expect(validateCommandForm(form({ command: 'say', values: { line_id: 'goodbye' } })).ok).toBe(
      true,
    );
    expect(validateCommandForm(form({ command: 'say', values: { line_id: 'Good bye' } })).ok).toBe(
      false,
    );
    expect(
      validateCommandForm(form({ command: 'play_motion', values: { name: 'wave-2' } })).ok,
    ).toBe(false);
    const long = validateCommandForm(
      form({ command: 'say_text', values: { text: 'x'.repeat(301) } }),
    );
    expect(long.ok).toBe(false);
  });
});

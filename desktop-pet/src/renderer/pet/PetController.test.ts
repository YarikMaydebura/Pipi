import type { BrainToBody, EyeState } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import { PetController, type MigrationService, type PetServices } from './PetController';
import type { PetView } from './PetView';

interface FakeView extends PetView {
  readonly log: string[];
}

function fakeView(knownMotions: readonly string[] = ['nod', 'wake_up', 'sleep']): FakeView {
  const log: string[] = [];
  return {
    kind: 'fallback',
    log,
    setEyeState: (state: EyeState) => log.push(`eyes:${state}`),
    playMotion: (name: string) => {
      log.push(`motion:${name}`);
      return knownMotions.includes(name);
    },
    setCursor: () => undefined,
    hitTest: () => false,
    setBaseMotion: (name: string, interrupt: boolean) => {
      log.push(`base:${name}${interrupt ? '!' : ''}`);
      return true;
    },
    flashFace: (face) => log.push(`face:${face ? (face.eyes ?? 'cheeks') : 'clear'}`),
    setMouthOverride: (shape) => log.push(`mouth:${shape ?? 'auto'}`),
    setCheeks: (on: boolean) => log.push(`cheeks:${on}`),
    setChestPulse: (on: boolean) => log.push(`chest:${on}`),
    setSpeechLevel: (level: number) => log.push(`level:${level}`),
    setReducedMotion: () => undefined,
    dispose: () => log.push('dispose'),
  };
}

function fakeServices(log: string[], failMigration = false): PetServices {
  const step = (name: string) => async (): Promise<void> => {
    log.push(name);
    if (failMigration) throw new Error('window gone');
  };
  const migration: MigrationService = {
    setRobotSide: async (side) => {
      log.push(`side:${side}`);
    },
    jumpOut: step('jumpOut'),
    jumpIn: step('jumpIn'),
    fadeOut: step('fadeOut'),
    fadeIn: step('fadeIn'),
    appear: step('appear'),
  };
  return {
    speech: {
      speak: async (request) => {
        log.push(`speak:${request.text}:${request.audio_b64 ? 'audio' : 'none'}`);
        return { ok: true };
      },
      interrupt: () => log.push('interrupt'),
    },
    caption: {
      show: (text) => log.push(`caption:${text}`),
      hide: () => log.push('caption:hide'),
    },
    migration,
  };
}

const envelope = { id: 'm1', ts: 1 };

describe('PetController', () => {
  it('routes eyes messages to the view', async () => {
    const view = fakeView();
    const result = await new PetController(view).handle({
      type: 'eyes',
      state: 'happy',
      ...envelope,
    });
    expect(result.ok).toBe(true);
    expect(view.log).toEqual(['eyes:happy']);
  });

  it('acks unknown motions with an error', async () => {
    const pet = new PetController(fakeView());
    expect((await pet.handle({ type: 'motion', name: 'nod', ...envelope })).ok).toBe(true);
    const bad = await pet.handle({ type: 'motion', name: 'moonwalk', ...envelope });
    expect(bad.ok).toBe(false);
    expect(bad.error).toContain('moonwalk');
  });

  it('shows the speak expression and hands the speech to the speech service', async () => {
    const view = fakeView();
    const log: string[] = [];
    const message: BrainToBody = {
      type: 'speak',
      text: 'hi',
      audio_b64: 'UklGRg==',
      expression: 'surprised',
      ...envelope,
    };
    await new PetController(view, fakeServices(log)).handle(message);
    expect(view.log).toContain('eyes:surprised');
    expect(log).toEqual(['speak:hi:audio']);
  });

  it('shows and hides captions', async () => {
    const log: string[] = [];
    const pet = new PetController(fakeView(), fakeServices(log));
    await pet.handle({ type: 'caption', text: 'Break time!', ...envelope });
    await pet.handle({ type: 'caption', text: null, ...envelope });
    expect(log).toEqual(['caption:Break time!', 'caption:hide']);
  });

  it('wakes up and goes to sleep', async () => {
    const view = fakeView();
    const pet = new PetController(view);
    await pet.handle({ type: 'activate', entrance: 'wake_up', ...envelope });
    await pet.handle({ type: 'deactivate', exit: 'sleep', ...envelope });
    expect(view.log).toEqual(['eyes:idle', 'motion:wake_up', 'motion:sleep', 'eyes:sleepy']);
  });

  it('jumps out (stopping speech first) and back in through the migration service', async () => {
    const log: string[] = [];
    const pet = new PetController(fakeView(), fakeServices(log));
    await pet.handle({ type: 'body_config', robot_side: 'left', ...envelope });
    const out = await pet.handle({ type: 'deactivate', exit: 'jump_out', ...envelope });
    const back = await pet.handle({ type: 'activate', entrance: 'jump_in', ...envelope });
    await pet.handle({ type: 'deactivate', exit: 'fade_out', ...envelope });
    await pet.handle({ type: 'activate', entrance: 'fade_in', ...envelope });
    expect(out.ok && back.ok).toBe(true);
    expect(log).toEqual([
      'side:left',
      'interrupt',
      'caption:hide',
      'jumpOut',
      'jumpIn',
      'interrupt',
      'caption:hide',
      'fadeOut',
      'fadeIn',
    ]);
  });

  it('acks a failed migration with the reason', async () => {
    const pet = new PetController(fakeView(), fakeServices([], true));
    const result = await pet.handle({ type: 'deactivate', exit: 'jump_out', ...envelope });
    expect(result).toEqual({ ok: false, error: 'jump_out failed: window gone' });
  });

  it('keeps eye state, cheeks, chest pulse and mouth override when the view is replaced', () => {
    const first = fakeView();
    const pet = new PetController(first);
    pet.setEyeState('thinking');
    pet.setEyeState('blink'); // one-shot, must not become the remembered state
    pet.setCheeks(true);
    pet.setMouthOverride('wavy');
    expect(first.log).toContain('mouth:wavy');
    const second = fakeView();
    pet.replaceView(second);
    expect(first.log).toContain('dispose');
    expect(second.log).toEqual([
      'eyes:thinking',
      'base:idle!',
      'cheeks:true',
      'chest:false',
      'mouth:wavy',
    ]);
    expect(pet.currentView).toBe(second);
  });

  it('reports what the brain is doing to the interaction layer', async () => {
    const pet = new PetController(fakeView(), fakeServices([]));
    const seen: string[] = [];
    pet.setActivityListener((activity, motion) =>
      seen.push(motion ? `${activity}+${motion}` : activity),
    );
    await pet.handle({ type: 'eyes', state: 'listening', ...envelope });
    await pet.handle({ type: 'eyes', state: 'blink', ...envelope }); // keeps listening
    await pet.handle({ type: 'eyes', state: 'thinking', ...envelope });
    pet.setTalking(true);
    pet.setTalking(true); // no change, no report
    pet.setTalking(false);
    await pet.handle({ type: 'motion', name: 'nod', ...envelope });
    await pet.handle({ type: 'eyes', state: 'happy', ...envelope });
    expect(seen).toEqual([
      'listening',
      'listening',
      'thinking',
      'speaking',
      'thinking',
      'thinking+nod',
      'idle',
    ]);
  });

  it('reports migrating during a jump and away after it, back to idle on return', async () => {
    const pet = new PetController(fakeView(), fakeServices([]));
    const seen: string[] = [];
    pet.setActivityListener((activity) => seen.push(activity));
    await pet.handle({ type: 'deactivate', exit: 'jump_out', ...envelope });
    expect(pet.activity).toBe('away');
    await pet.handle({ type: 'activate', entrance: 'jump_in', ...envelope });
    await pet.handle({ type: 'deactivate', exit: 'sleep', ...envelope });
    expect(seen).toEqual(['migrating', 'away', 'migrating', 'idle', 'asleep']);
  });

  it('stays on screen (not away) when the jump out fails', async () => {
    const pet = new PetController(fakeView(), fakeServices([], true));
    await pet.handle({ type: 'deactivate', exit: 'jump_out', ...envelope });
    expect(pet.activity).toBe('idle');
  });

  it('dozes with sleepy eyes and wakes back to the eye state the brain asked for', async () => {
    const view = fakeView();
    const pet = new PetController(view);
    await pet.handle({ type: 'eyes', state: 'determined', ...envelope });
    pet.setDozing(true);
    pet.setDozing(false);
    expect(view.log).toEqual(['eyes:determined', 'eyes:sleepy', 'eyes:determined']);
    expect(pet.currentEyeState).toBe('determined');
  });

  it('forwards reaction steps to the view', () => {
    const view = fakeView();
    const pet = new PetController(view);
    pet.setBaseMotion('dangle', true);
    pet.flashFace({ eyes: 'love', durationMs: 500 });
    pet.flashFace(null);
    expect(view.log).toEqual(['base:dangle!', 'face:love', 'face:clear']);
  });
});

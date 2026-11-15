import { describe, expect, it } from 'vitest';
import type { WindowCommand } from '../../preload/bridge';
import { applySpeechLevel, computeEyeFrame } from '@pipi/shared/look';
import { MOTIONS } from '../motion/motions';
import { Migrator, type WindowControl } from './migrator';
import { enterKeyframes, leaveKeyframes, type StageMotion } from './stageMotion';

function setup(options: { window?: boolean; reject?: boolean } = {}) {
  const log: string[] = [];
  const window: WindowControl = {
    command: async (command: WindowCommand) => {
      log.push(`window:${command.action}${'side' in command ? `:${command.side}` : ''}`);
      return !options.reject;
    },
  };
  const stage: StageMotion = {
    leave: async (side) => {
      log.push(`leave:${side}`);
    },
    placeOutside: (side) => log.push(`outside:${side}`),
    enter: async (side) => {
      log.push(`enter:${side}`);
    },
    fade: async (visible) => {
      log.push(`fade:${visible}`);
    },
    reset: () => log.push('reset'),
  };
  const migrator = new Migrator({
    window: options.window === false ? null : window,
    stage,
    view: () => ({
      playMotion: (name: string) => {
        log.push(`motion:${name}`);
        return true;
      },
    }),
    wait: async () => undefined,
  });
  return { migrator, log };
}

describe('Migrator', () => {
  it('moves to the robot-side corner once the side is known', async () => {
    const { migrator, log } = setup();
    await migrator.setRobotSide('right'); // first config: place even if it is the default
    await migrator.setRobotSide('right'); // same again: stay where the user put Pipi
    await migrator.setRobotSide('left');
    expect(log).toEqual(['window:place:right', 'window:place:left']);
  });

  it('jumps out: hops to the edge, leaps over it, hides the window', async () => {
    const { migrator, log } = setup();
    await migrator.setRobotSide('left');
    log.length = 0;
    await migrator.jumpOut();
    expect(log).toEqual([
      'motion:hop',
      'window:slide:left',
      'motion:hop',
      'motion:jump_out',
      'leave:left',
      'window:hide',
      'reset',
      'motion:idle',
    ]);
    expect(migrator.isAway).toBe(true);
    await migrator.jumpOut(); // already away: nothing happens
    expect(log.filter((entry) => entry === 'leave:left')).toHaveLength(1);
  });

  it('jumps in from the robot side', async () => {
    const { migrator, log } = setup();
    await migrator.jumpOut();
    log.length = 0;
    await migrator.jumpIn();
    expect(log).toEqual(['outside:right', 'window:show:right', 'motion:jump_in', 'enter:right']);
    expect(migrator.isAway).toBe(false);
  });

  it('works without the Electron bridge (plain browser)', async () => {
    const { migrator, log } = setup({ window: false });
    await migrator.jumpOut();
    await migrator.jumpIn();
    expect(log.some((entry) => entry.startsWith('window:'))).toBe(false);
    expect(log).toContain('leave:right');
    expect(log).toContain('enter:right');
  });

  it('reports a rejected window command as an error', async () => {
    const { migrator } = setup({ reject: true });
    await expect(migrator.jumpIn()).rejects.toThrow("window command 'show' was rejected");
    await expect(migrator.fadeOut()).rejects.toThrow('hide'); // the queue keeps working
  });

  it('runs one migration at a time', async () => {
    const { migrator, log } = setup();
    await Promise.all([migrator.jumpOut(), migrator.jumpIn()]);
    expect(log.indexOf('window:hide')).toBeLessThan(log.indexOf('window:show:right'));
  });
});

describe('migration keyframes and motions', () => {
  it('leaves toward the robot side and ends invisible', () => {
    const right = leaveKeyframes('right');
    const left = leaveKeyframes('left');
    expect(right.at(-1)?.opacity).toBe(0);
    expect(String(right.at(-1)?.transform)).toContain('translate(125%');
    expect(String(left.at(-1)?.transform)).toContain('translate(-125%');
  });

  it('enters from the robot side and ends at rest', () => {
    const frames = enterKeyframes('left');
    expect(String(frames[0]?.transform)).toContain('translate(-120%');
    expect(frames.at(-1)?.transform).toBe('translate(0%, 0%) rotate(0deg)');
  });

  it('has procedural jump motions that crouch before leaping and squash on landing', () => {
    const out = MOTIONS['jump_out'];
    const into = MOTIONS['jump_in'];
    expect(out?.sample(0.15).squash).toBeGreaterThan(0.05);
    expect(out?.sample(0.6).bodyLift).toBeGreaterThan(0.05);
    expect(into?.sample(0.5).squash).toBeGreaterThan(0.05);
  });
});

describe('speech glow', () => {
  it('brightens and stretches the eyes with the voice, but not when silent or off', () => {
    const frame = computeEyeFrame('idle', 0);
    expect(applySpeechLevel(frame, 0)).toBe(frame);
    const loud = applySpeechLevel(frame, 1);
    expect(loud.glow).toBeGreaterThan(frame.glow);
    expect(loud.height).toBeGreaterThan(frame.height);
    const off = computeEyeFrame('off', 0);
    expect(applySpeechLevel(off, 1)).toBe(off);
  });
});

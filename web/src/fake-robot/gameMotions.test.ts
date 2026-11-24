// Staring contest and arm rock-paper-scissors (docs/GAMES.md §3.3–3.4): the procedural motions
// the fake robot plays for them. The generic checks (one-shots start and end at rest, loops are
// seamless, joints stay in range) run for every procedural motion in motionPlan.test.ts.
import { describe, expect, it } from 'vitest';
import { RPS_CHOICE_MOTION_NAMES, STARE_RPS_MOTION_NAMES } from './gameMotions';
import { HELD_MOTIONS, planMotion } from './motionPlan';
import { PROCEDURAL_MOTIONS, type RobotPose } from './proceduralMotions';

function motion(name: string): NonNullable<(typeof PROCEDURAL_MOTIONS)[string]> {
  const def = PROCEDURAL_MOTIONS[name];
  if (!def) throw new Error(`no procedural motion ${name}`);
  return def;
}

const at = (name: string, p: number): RobotPose => motion(name).sample(p);

/** max − min of one pose field over the whole motion. */
function range(name: string, key: keyof RobotPose): number {
  const values = Array.from({ length: 201 }, (_, i) => at(name, i / 200)[key]);
  return Math.max(...values) - Math.min(...values);
}

const NO_CLIPS = (): boolean => false;
const HELD = ['stare_ready', 'rps_rock', 'rps_paper', 'rps_scissors'];
const ONCE = ['stare_lose', 'rps_shake'];

describe('staring and rps motions: registry and modes', () => {
  it('registers all six as procedural motions', () => {
    expect([...STARE_RPS_MOTION_NAMES].sort()).toEqual([...HELD, ...ONCE].sort());
    for (const name of STARE_RPS_MOTION_NAMES) {
      expect(planMotion(name, NO_CLIPS), name).toMatchObject({ kind: 'procedural', name });
    }
  });

  it('holds the stance and the three choices until the next motion', () => {
    for (const name of HELD) {
      expect(HELD_MOTIONS, name).toContain(name);
      expect(motion(name).loop, name).toBe(true);
      expect(planMotion(name, NO_CLIPS), name).toMatchObject({ mode: 'held' });
    }
  });

  it('plays the lose reaction and the count-down pump once', () => {
    for (const name of ONCE) {
      expect(HELD_MOTIONS, name).not.toContain(name);
      expect(motion(name).loop, name).toBe(false);
      expect(planMotion(name, NO_CLIPS), name).toMatchObject({ mode: 'once' });
    }
  });
});

describe('stare_ready', () => {
  it('leans in with the face kept square to the participant', () => {
    const stance = at('stare_ready', 0.3);
    expect(stance.bodyBow).toBeGreaterThan(0.06);
    expect(stance.headPitch).toBeLessThan(0); // chin up against the lean: eyes stay level
    expect(Math.abs(stance.headPitch + stance.bodyBow)).toBeLessThan(0.05);
    expect(stance.headYaw).toBe(0);
  });

  it('is almost motionless: only a breath, the head does not wander', () => {
    for (const key of ['headYaw', 'headRoll', 'bodyYaw', 'bodyLean'] as const) {
      expect(range('stare_ready', key), key).toBeLessThan(0.005);
    }
    for (const key of ['headPitch', 'bodyBow', 'armLRaise', 'armRForward'] as const) {
      expect(range('stare_ready', key), key).toBeLessThan(0.03);
    }
    expect(range('stare_ready', 'bodyLift')).toBeGreaterThan(0); // not frozen
  });

  it('is a different stance from the duel', () => {
    const stare = at('stare_ready', 0.5);
    const duel = at('duel_ready', 0.5);
    expect(stare.armLRaise).toBeLessThan(duel.armLRaise - 0.2); // arms relaxed, not hovering out
    expect(stare.headPitch).toBeLessThan(duel.headPitch); // looking at you, not down
  });
});

describe('stare_lose', () => {
  it('snaps the head back first', () => {
    const def = motion('stare_lose');
    expect(def.attackS ?? 0.3).toBeLessThan(0.1);
    const flinch = at('stare_lose', 0.08);
    expect(flinch.headPitch).toBeLessThan(-0.2);
    expect(flinch.bodyBow).toBeLessThan(-0.1);
    expect(0.08 * def.durationS).toBeLessThan(0.3); // within a fraction of a second
  });

  it('turns away and brings both hands up to the eyes, rubbing them', () => {
    const covering = at('stare_lose', 0.45);
    expect(covering.headYaw + covering.bodyYaw).toBeGreaterThan(0.5);
    for (const side of ['L', 'R'] as const) {
      expect(covering[`arm${side}Forward`], side).toBeGreaterThan(1);
      expect(covering[`elbow${side}Bend`], side).toBeGreaterThan(1.6);
    }
    // rubbing: the forearms move against each other while the hands are up
    const rub = Array.from({ length: 41 }, (_, i) => at('stare_lose', 0.3 + (0.35 * i) / 40));
    const spread = rub.map((pose) => pose.elbowLBend - pose.elbowRBend);
    expect(Math.max(...spread) - Math.min(...spread)).toBeGreaterThan(0.15);
  });
});

describe('rps_shake', () => {
  it('is one clear beat of about half a second, starting without a fade', () => {
    const def = motion('rps_shake');
    expect(def.durationS).toBeGreaterThanOrEqual(0.5);
    expect(def.durationS).toBeLessThanOrEqual(0.65);
    expect(def.attackS ?? 0.3).toBeLessThan(0.1);
  });

  it('raises both fists, then pumps them down', () => {
    const forward = Array.from({ length: 101 }, (_, i) => at('rps_shake', i / 100).armRForward);
    const top = forward.indexOf(Math.max(...forward));
    expect(forward[top]).toBeGreaterThan(1);
    expect(top / 100).toBeLessThan(0.5); // up in the first half…
    expect(at('rps_shake', 0.62).armRForward).toBeLessThan((forward[top] ?? 0) - 0.5); // …then down
    for (const p of [0.2, 0.4, 0.6, 0.8]) {
      expect(at('rps_shake', p).armLForward).toBeCloseTo(at('rps_shake', p).armRForward, 6);
    }
  });
});

describe('rps choices', () => {
  it('rock: both arms down and tucked in, the body set low', () => {
    const rock = at('rps_rock', 0.4);
    for (const side of ['L', 'R'] as const) {
      expect(rock[`arm${side}Raise`], side).toBeLessThan(0.4);
      expect(rock[`arm${side}Forward`], side).toBeLessThan(0.6);
    }
    expect(rock.bodyLift).toBeLessThan(0);
  });

  it('paper: both arms wide open to the sides', () => {
    const paper = at('rps_paper', 0.4);
    expect(paper.armLRaise).toBeGreaterThan(1.2);
    expect(paper.armRRaise).toBeGreaterThan(1.2);
    expect(paper.elbowLBend).toBeLessThan(0.3); // straight arms
  });

  it('scissors: both arms cross in front of the body', () => {
    const scissors = at('rps_scissors', 0.4);
    expect(scissors.armLRaise).toBeLessThan(-0.2); // - = across the body
    expect(scissors.armRRaise).toBeLessThan(-0.2);
    expect(scissors.armLForward).toBeGreaterThan(0.4);
  });

  it('hold their shape: they barely move while Pipi judges', () => {
    for (const name of RPS_CHOICE_MOTION_NAMES) {
      for (const key of ['armLRaise', 'armRRaise', 'armLForward', 'armRForward'] as const) {
        expect(range(name, key), `${name}.${key}`).toBeLessThan(0.08);
      }
    }
  });

  it('show their choice quickly on "shoot!"', () => {
    for (const name of RPS_CHOICE_MOTION_NAMES) {
      expect(motion(name).attackS ?? 0.3, name).toBeLessThan(0.2);
    }
  });
});

import {
  AnimationClip,
  AnimationMixer,
  Euler,
  Group,
  Object3D,
  Quaternion,
  QuaternionKeyframeTrack,
} from 'three';
import { describe, expect, it } from 'vitest';
import { pose, ZERO_POSE, type Pose } from '../motion/pose';
import { RigPoser, type RobotRig } from './robotRig';

const FRAME_S = 1 / 60;
const FRAMES = 6;
const HEAD_YAW = 0.2;
/** Decimal places for angles in radians: clip values are float32, so 1e-4 is noise. */
const ANGLE_DIGITS = 3;
/** What the clip says: the head leans forward and stays there. */
const LEAN = new Quaternion().setFromEuler(new Euler(0.12, 0, 0));

interface Fixture {
  readonly head: Object3D;
  /** One frame, in the same order as Pet3DView.renderFrame. */
  readonly frame: (p: Pose) => void;
}

/** A rig with one bone. With `withClip`, a looping clip HOLDS it in LEAN (same value every frame). */
function setup(withClip: boolean): Fixture {
  const model = new Object3D();
  const head = new Object3D();
  head.name = 'head';
  model.add(head);
  const poseRoot = new Group();
  poseRoot.add(model);
  poseRoot.updateMatrixWorld(true);
  const rig: RobotRig = { poseRoot, model, bones: { head } };
  const poser = new RigPoser(rig);

  const mixer = new AnimationMixer(model);
  if (withClip) {
    const values = [...LEAN.toArray(), ...LEAN.toArray()];
    const track = new QuaternionKeyframeTrack('head.quaternion', [0, 1], values);
    mixer.clipAction(new AnimationClip('held', 1, [track])).play();
  }
  const frame = (p: Pose): void => {
    poser.restoreClipPose();
    mixer.update(FRAME_S);
    poser.saveClipPose();
    poser.apply(p);
  };
  return { head, frame };
}

describe('RigPoser with animation clips', () => {
  it('keeps a pose that the clip holds still on every frame', () => {
    // The three.js mixer only writes a bone when its value changed since the previous frame,
    // so a held pose is written once. The bone must not fall back to the rest pose after that.
    const { head, frame } = setup(true);

    for (let i = 0; i < FRAMES; i += 1) {
      frame(ZERO_POSE);

      expect(head.quaternion.angleTo(LEAN)).toBeCloseTo(0, ANGLE_DIGITS);
    }
  });

  it('adds the procedural pose on top of the clip pose without piling up', () => {
    const { head, frame } = setup(true);
    const turn = new Quaternion().setFromEuler(new Euler(0, HEAD_YAW, 0, 'YXZ'));
    const expected = LEAN.clone().premultiply(turn);

    for (let i = 0; i < FRAMES; i += 1) {
      frame(pose({ headYaw: HEAD_YAW }));

      expect(head.quaternion.angleTo(expected)).toBeCloseTo(0, ANGLE_DIGITS);
    }
  });

  it('goes back to the rest pose when there is no clip and the pose ends', () => {
    const { head, frame } = setup(false);
    const rest = head.quaternion.clone();

    frame(pose({ headYaw: HEAD_YAW }));
    frame(ZERO_POSE);

    expect(head.quaternion.angleTo(rest)).toBeCloseTo(0, ANGLE_DIGITS);
  });
});

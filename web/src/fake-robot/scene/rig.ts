// Turns a loaded model (alpha_mini.glb or the stand-in) into something we can pose: normalised to
// height 1 with the feet at the origin, live eye materials installed, shadows on, and the bones
// that procedural motions move (head, shoulders) found by name. Procedural poses are
// added on top of the clips in MODEL space, so they work whatever local axes the bones have.
import {
  Box3,
  Euler,
  Group,
  Mesh,
  MeshStandardMaterial,
  Quaternion,
  Vector3,
  type Material,
  type Object3D,
} from 'three';
import type { RobotPose } from '../proceduralMotions';

export const BONES = {
  head: 'head',
  shoulderL: 'shoulder.L',
  shoulderR: 'shoulder.R',
} as const;
type BoneKey = keyof typeof BONES;

export const EYE_L = 'EyeL';
export const EYE_R = 'EyeR';
export const EYE_MATERIAL = 'EyeScreen';
/** Chest badge (blue dots); its glow pulses while the robot speaks. */
export const BADGE_MATERIAL = 'PipiBlueGlow';

/** Case-insensitive, ignoring separators and a ".001" suffix ("shoulder.L" → "shoulderL"). */
export function normalizeName(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[._]?\d{3}$/, '')
    .replace(/[\s._\-:/]/g, '');
}

const matches = (actual: string, wanted: string): boolean =>
  normalizeName(actual) === normalizeName(wanted);

export interface Rig {
  /** Outer group at the feet: whole-body lift / lean / bow. Add this to the scene. */
  readonly root: Group;
  readonly model: Object3D;
  readonly bones: Readonly<Partial<Record<BoneKey, Object3D>>>;
  /** Materials of the chest badge (empty if the model has none). */
  readonly badge: readonly MeshStandardMaterial[];
  readonly eyesFound: boolean;
}

function materialsOf(mesh: Mesh): Material[] {
  return Array.isArray(mesh.material) ? mesh.material : [mesh.material];
}

function normalise(model: Object3D): Group {
  model.updateMatrixWorld(true);
  const box = new Box3().setFromObject(model);
  const size = box.getSize(new Vector3());
  const scale = size.y > 0 ? 1 / size.y : 1;
  const center = box.getCenter(new Vector3());
  const wrapper = new Group();
  wrapper.name = 'RobotNormaliser';
  wrapper.scale.setScalar(scale);
  wrapper.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
  wrapper.add(model);
  return wrapper;
}

export function buildRig(model: Object3D, eyes: { left: Material; right: Material }): Rig {
  const root = new Group();
  root.name = 'RobotPoseRoot';
  root.add(normalise(model));
  root.updateMatrixWorld(true);

  const bones: Partial<Record<BoneKey, Object3D>> = {};
  const badge = new Set<MeshStandardMaterial>();
  let eyesFound = false;
  model.traverse((object) => {
    for (const key of Object.keys(BONES) as BoneKey[]) {
      if (!bones[key] && matches(object.name, BONES[key])) bones[key] = object;
    }
    if (!(object instanceof Mesh)) return;
    object.castShadow = true;
    object.receiveShadow = true;
    if (matches(object.name, EYE_R)) {
      object.material = eyes.right;
      eyesFound = true;
    } else if (
      matches(object.name, EYE_L) ||
      materialsOf(object).some((m) => matches(m.name, EYE_MATERIAL))
    ) {
      object.material = eyes.left;
      eyesFound = true;
    }
    for (const material of materialsOf(object)) {
      if (material instanceof MeshStandardMaterial && matches(material.name, BADGE_MATERIAL)) {
        badge.add(material);
      }
    }
  });
  for (const key of Object.keys(BONES) as BoneKey[]) {
    if (!bones[key]) console.warn(`[fake robot] bone "${BONES[key]}" not found; it will not move`);
  }
  if (!eyesFound) console.warn('[fake robot] model has no EyeL/EyeR meshes: no eye displays');
  return { root, model, bones, badge: [...badge], eyesFound };
}

interface BoneRest {
  readonly local: Quaternion;
  readonly parent: Quaternion; // parent's rest rotation relative to the pose root
  readonly parentInverse: Quaternion;
}

/** resetToRest() → clips update → apply(pose), every frame. */
export class RigPoser {
  private readonly rest = new Map<Object3D, BoneRest>();
  private readonly euler = new Euler();
  private readonly delta = new Quaternion();

  constructor(private readonly rig: Rig) {
    const rootInverse = rig.root.getWorldQuaternion(new Quaternion()).invert();
    for (const bone of Object.values(rig.bones)) {
      const parent = bone.parent
        ? bone.parent.getWorldQuaternion(new Quaternion()).premultiply(rootInverse)
        : new Quaternion();
      this.rest.set(bone, {
        local: bone.quaternion.clone(),
        parent,
        parentInverse: parent.clone().invert(),
      });
    }
  }

  resetToRest(): void {
    for (const [bone, rest] of this.rest) bone.quaternion.copy(rest.local);
  }

  private rotate(bone: Object3D | undefined, x: number, y: number, z: number): void {
    if (!bone || (x === 0 && y === 0 && z === 0)) return;
    const rest = this.rest.get(bone);
    if (!rest) return;
    // Model-space rotation D expressed in the parent's frame: P⁻¹ · D · P.
    this.delta.setFromEuler(this.euler.set(x, y, z, 'YXZ'));
    this.delta.premultiply(rest.parentInverse).multiply(rest.parent);
    bone.quaternion.premultiply(this.delta);
  }

  apply(p: RobotPose): void {
    const { root, bones } = this.rig;
    root.position.y = p.bodyLift;
    root.rotation.set(p.bodyBow, 0, -p.bodyLean);
    this.rotate(bones.head, p.headPitch, p.headYaw, -p.headRoll);
    // The robot's left arm is on +X: raising it sideways is +Z rotation; the right arm mirrors.
    this.rotate(bones.shoulderL, -p.armLForward, 0, p.armLRaise);
    this.rotate(bones.shoulderR, -p.armRForward, 0, -p.armRRaise);
  }
}

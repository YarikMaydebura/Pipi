// Turns a loaded model (glb or placeholder) into a rig: finds the named bones, normalises the
// size, installs the live eye and mouth materials, and adds procedural Poses on top of animation clips.
import { Box3, Euler, Group, Mesh, Quaternion, Vector3, type Material, type Object3D } from 'three';
import type { Pose } from '../motion/pose';
import { eyeGeometry } from './eyeGeometry';
import {
  BONE_NAMES,
  EYE_L_NAME,
  EYE_MATERIAL_NAME,
  EYE_R_NAME,
  MOUTH_MATERIAL_NAME,
  MOUTH_NAME,
  namesMatch,
  type BoneKey,
} from './partNames';

export interface RobotRig {
  /** Outer group at the feet; moves/bows/squashes the whole robot. Add this to the scene. */
  readonly poseRoot: Group;
  readonly model: Object3D;
  readonly bones: Readonly<Partial<Record<BoneKey, Object3D>>>;
}

export interface FaceMaterials {
  readonly left: Material;
  readonly right: Material;
  readonly mouth: Material;
}

type EyeMaterials = Pick<FaceMaterials, 'left' | 'right'>;

/** Robot height in scene units after normalisation. */
export const ROBOT_HEIGHT = 1;

function findByName(root: Object3D, wanted: string): Object3D | undefined {
  let found: Object3D | undefined;
  root.traverse((object) => {
    if (!found && namesMatch(object.name, wanted)) found = object;
  });
  return found;
}

function hasMaterial(mesh: Mesh, wanted: string): boolean {
  const materials: Material[] = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  return materials.some((m) => namesMatch(m.name, wanted));
}

/** Scale the model to ROBOT_HEIGHT and put the middle of its feet at the origin. */
function normalise(model: Object3D): Group {
  model.updateMatrixWorld(true);
  const box = new Box3().setFromObject(model);
  const size = box.getSize(new Vector3());
  const scale = size.y > 0 ? ROBOT_HEIGHT / size.y : 1;
  const center = box.getCenter(new Vector3());
  const wrapper = new Group();
  wrapper.name = 'PipiNormaliser';
  wrapper.scale.setScalar(scale);
  wrapper.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
  wrapper.add(model);
  return wrapper;
}

/** No eye meshes in the model: put two eye quads on the front of the upper body. */
function attachFallbackEyes(model: Object3D, materials: EyeMaterials): void {
  console.warn('[pipi] model has no EyeL/EyeR meshes or "EyeScreen" material; adding eye quads');
  const box = new Box3().setFromObject(model);
  const size = box.getSize(new Vector3());
  const eyeSize = size.x * 0.22;
  const y = box.min.y + size.y * 0.7;
  const z = box.max.z + 0.002;
  const eyeL = new Mesh(eyeGeometry(eyeSize, false), materials.left);
  eyeL.position.set(box.min.x + size.x * 0.68, y, z);
  const eyeR = new Mesh(eyeGeometry(eyeSize, true), materials.right);
  eyeR.position.set(box.min.x + size.x * 0.32, y, z);
  model.attach(eyeL); // attach() keeps the world transform
  model.attach(eyeR);
}

/** Give EyeL / EyeR their live materials (anything else using "EyeScreen" gets the left one). */
function installEyeMaterials(model: Object3D, materials: EyeMaterials): void {
  let count = 0;
  model.traverse((object) => {
    if (!(object instanceof Mesh)) return;
    if (namesMatch(object.name, EYE_R_NAME)) object.material = materials.right;
    else if (namesMatch(object.name, EYE_L_NAME) || hasMaterial(object, EYE_MATERIAL_NAME)) {
      object.material = materials.left;
    } else return;
    count += 1;
  });
  if (count === 0) attachFallbackEyes(model, materials);
}

/** Give the "Mouth" mesh (or anything using "MouthScreen") the live mouth material. */
function installMouthMaterial(model: Object3D, mouth: Material): void {
  let count = 0;
  model.traverse((object) => {
    if (!(object instanceof Mesh)) return;
    if (!namesMatch(object.name, MOUTH_NAME) && !hasMaterial(object, MOUTH_MATERIAL_NAME)) return;
    object.material = mouth;
    count += 1;
  });
  if (count === 0) console.warn('[pipi] model has no "Mouth" mesh; the face has no mouth');
}

export function buildRig(model: Object3D, faceMaterials: FaceMaterials): RobotRig {
  const poseRoot = new Group();
  poseRoot.name = 'PipiPoseRoot';
  poseRoot.add(normalise(model));
  poseRoot.updateMatrixWorld(true);

  const bones: Partial<Record<BoneKey, Object3D>> = {};
  for (const key of Object.keys(BONE_NAMES) as BoneKey[]) {
    const bone = findByName(model, BONE_NAMES[key]);
    if (bone) bones[key] = bone;
    else console.warn(`[pipi] bone "${BONE_NAMES[key]}" not found; it will not animate`);
  }
  installEyeMaterials(model, faceMaterials);
  installMouthMaterial(model, faceMaterials.mouth);
  return { poseRoot, model, bones };
}

interface BoneRest {
  /** The parent's rest rotation relative to the pose root (to rotate in model space). */
  readonly parent: Quaternion;
  readonly parentInverse: Quaternion;
  /** What the animation clips last set this bone to (the rest pose until a clip moves it). */
  readonly clip: Quaternion;
}

/**
 * Adds Poses on top of the rest pose (or of an animation clip): restoreClipPose() → clips
 * update → saveClipPose() → apply(pose). Rotations are given in model space (X right, Y up, Z toward the viewer), so
 * they work whatever local axes the Blender bones have.
 */
export class RigPoser {
  private readonly rest = new Map<Object3D, BoneRest>();
  private readonly euler = new Euler();
  private readonly delta = new Quaternion();

  constructor(private readonly rig: RobotRig) {
    const rootInverse = rig.poseRoot.getWorldQuaternion(new Quaternion()).invert();
    for (const bone of Object.values(rig.bones)) {
      const parent = bone.parent
        ? bone.parent.getWorldQuaternion(new Quaternion()).premultiply(rootInverse)
        : new Quaternion();
      this.rest.set(bone, {
        parent,
        parentInverse: parent.clone().invert(),
        clip: bone.quaternion.clone(),
      });
    }
  }

  /**
   * Undo the previous apply(): every posed bone goes back to what the clips last said (the
   * rest pose until a clip moves it). Call before the animation mixer updates. It must not be
   * the rest pose: the mixer only writes a bone when its value changed since the previous
   * frame, so a bone that a clip holds still would stay at rest and snap back a moment later.
   */
  restoreClipPose(): void {
    for (const [bone, rest] of this.rest) bone.quaternion.copy(rest.clip);
  }

  /** Remember what the clips say (call right after the mixer update, before apply()). */
  saveClipPose(): void {
    for (const [bone, rest] of this.rest) rest.clip.copy(bone.quaternion);
  }

  private rotate(bone: Object3D | undefined, x: number, y: number, z: number): void {
    if (!bone || (x === 0 && y === 0 && z === 0)) return;
    const rest = this.rest.get(bone);
    if (!rest) return;
    // delta in the parent's frame = P⁻¹ · D · P, where D is the model-space rotation.
    this.delta.setFromEuler(this.euler.set(x, y, z, 'YXZ'));
    this.delta.premultiply(rest.parentInverse).multiply(rest.parent);
    bone.quaternion.premultiply(this.delta);
  }

  apply(p: Pose): void {
    const { poseRoot, bones } = this.rig;
    poseRoot.position.y = p.bodyLift;
    poseRoot.rotation.set(p.bodyBow, p.bodyYaw, -p.bodyLean);
    poseRoot.scale.set(1 + p.squash / 2, 1 - p.squash, 1 + p.squash / 2);

    this.rotate(bones.head, p.headPitch, p.headYaw, -p.headRoll);
    // The robot's left arm is on +X: raising it sideways is +Z rotation; the right arm mirrors.
    this.rotate(bones.shoulderL, -p.armLForward, 0, p.armLRaise);
    this.rotate(bones.shoulderR, -p.armRForward, 0, -p.armRRaise);
    this.rotate(bones.antennaBase, p.antennaPitch, 0, -p.antennaRoll);
  }
}

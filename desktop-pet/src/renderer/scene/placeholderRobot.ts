// A procedural stand-in for pipi.glb, built from three.js primitives: an original chibi robot
// (round head with a dark face screen, bean body, mitten hands, boots, antenna with a sprout).
// It follows the glb contract so the swap is seamless: groups are named like the glb bones
// (root, hips, spine, head, antenna_base, antenna_tip, shoulder.L/R, elbow.L/R, hand.L/R,
// thigh.L/R, shin.L/R, foot.L/R), meshes EyeL/EyeR/CheekL/CheekR/ChestLight/Sprout use the
// same material names (+ Mouth / MouthScreen), +Y up, faces +Z, robot's left = +X, origin between the feet.
// Units: total height ≈ 1 (the loader normalises every model to height 1 anyway).
import {
  CapsuleGeometry,
  CircleGeometry,
  CylinderGeometry,
  Group,
  Mesh,
  SphereGeometry,
  type BufferGeometry,
  type Material,
} from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { createRobotMaterials, type RobotMaterials } from './materials';
import { eyeGeometry } from './eyeGeometry';
import { EYE_L_NAME, EYE_R_NAME, MOUTH_NAME } from './partNames';

/** Head shell: an ellipsoid slightly wider than tall (radii in head-local units). */
const HEAD = { x: 0.28, y: 0.23, z: 0.21, centerY: 0.23 } as const;
const EYE_SIZE = 0.19;
const EYE_X = 0.1;
const EYE_Y = 0.02;
/** Mouth quad: one square image, the drawn mouth is ~60% of its width (≈ one eye's width). */
const MOUTH_SIZE = 0.12;
const MOUTH_Y = -0.085;

function mesh(name: string, geometry: BufferGeometry, material: Material): Mesh {
  const m = new Mesh(geometry, material);
  m.name = name;
  return m;
}

function group(name: string, x = 0, y = 0, z = 0): Group {
  const g = new Group();
  g.name = name;
  g.position.set(x, y, z);
  return g;
}

/**
 * Bend a flat geometry (in the XY plane, centred at the origin) onto the front of the head
 * ellipsoid, centred at (cx, cy) in head-shell coordinates, `lift` in front of the surface.
 */
function conformToHead(
  geometry: BufferGeometry,
  cx: number,
  cy: number,
  lift: number,
): BufferGeometry {
  const pos = geometry.getAttribute('position');
  const scale = 1 + lift;
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i) + cx;
    const y = pos.getY(i) + cy;
    const inside = Math.max(0, 1 - (x / HEAD.x) ** 2 - (y / HEAD.y) ** 2);
    pos.setXYZ(i, x, y + HEAD.centerY, HEAD.z * Math.sqrt(inside) * scale);
  }
  pos.needsUpdate = true;
  geometry.computeVertexNormals();
  return geometry;
}

function buildFace(head: Group, mats: RobotMaterials): void {
  // Dark glossy screen: the front patch of a slightly larger copy of the head ellipsoid.
  const screen = mesh(
    'FaceScreen',
    new SphereGeometry(1, 64, 32, Math.PI / 2 - 0.78, 1.56, Math.PI / 2 - 0.6, 1.2),
    mats.face,
  );
  screen.scale.set(HEAD.x * 1.008, HEAD.y * 1.008, HEAD.z * 1.008);
  screen.position.y = HEAD.centerY;

  const eyeL = mesh(
    EYE_L_NAME,
    conformToHead(eyeGeometry(EYE_SIZE, false), EYE_X, EYE_Y, 0.03),
    mats.eyePlaceholder,
  );
  const eyeR = mesh(
    EYE_R_NAME,
    conformToHead(eyeGeometry(EYE_SIZE, true), -EYE_X, EYE_Y, 0.03),
    mats.eyePlaceholder,
  );

  // Same quad + UV contract as an unmirrored eye: full 0–1 square, glTF V convention.
  const mouth = mesh(
    MOUTH_NAME,
    conformToHead(eyeGeometry(MOUTH_SIZE, false), 0, MOUTH_Y, 0.028),
    mats.mouthPlaceholder,
  );

  const cheekShape = (): BufferGeometry => new CircleGeometry(0.028, 32).scale(1.4, 0.8, 1);
  const cheekL = mesh('CheekL', conformToHead(cheekShape(), 0.145, -0.075, 0.025), mats.cheek);
  const cheekR = mesh('CheekR', conformToHead(cheekShape(), -0.145, -0.075, 0.025), mats.cheek);
  head.add(screen, eyeL, eyeR, mouth, cheekL, cheekR);
}

function buildAntenna(mats: RobotMaterials): Group {
  const base = group('antenna_base', 0, HEAD.centerY + HEAD.y - 0.01, 0);
  const stem = mesh('AntennaStem', new CylinderGeometry(0.01, 0.014, 0.075, 16), mats.belly);
  stem.position.y = 0.0375;
  const tip = group('antenna_tip', 0, 0.075, 0);
  const sprout = new Group();
  sprout.name = 'SproutLeaves';
  for (const side of [-1, 1]) {
    const leaf = mesh('Sprout', new SphereGeometry(1, 24, 12), mats.sprout);
    leaf.scale.set(0.045, 0.012, 0.024);
    leaf.position.set(side * 0.036, 0.016, 0);
    leaf.rotation.z = side * 0.5;
    sprout.add(leaf);
  }
  const bud = mesh('Sprout', new SphereGeometry(0.013, 16, 12), mats.sprout);
  sprout.add(bud);
  tip.add(sprout);
  base.add(stem, tip);
  return base;
}

function buildHead(mats: RobotMaterials): Group {
  const head = group('head', 0, 0.31, 0); // pivot at the neck
  const shell = mesh('HeadShell', new SphereGeometry(1, 64, 48), mats.shell);
  shell.scale.set(HEAD.x, HEAD.y, HEAD.z);
  shell.position.y = HEAD.centerY;
  head.add(shell, buildAntenna(mats));
  buildFace(head, mats);
  return head;
}

function buildArm(side: 'L' | 'R', mats: RobotMaterials): Group {
  const sign = side === 'L' ? 1 : -1;
  const shoulder = group(`shoulder.${side}`, 0.175 * sign, 0.24, 0);
  shoulder.rotation.z = 0.35 * sign; // rest pose: arms slightly away from the bean body
  const ball = mesh(`ShoulderBall.${side}`, new SphereGeometry(0.04, 24, 16), mats.shell);
  const upper = mesh(`UpperArm.${side}`, new CylinderGeometry(0.038, 0.033, 0.085, 24), mats.shell);
  upper.position.y = -0.045;

  const elbow = group(`elbow.${side}`, 0, -0.085, 0);
  const fore = mesh(`Forearm.${side}`, new CylinderGeometry(0.033, 0.029, 0.06, 24), mats.shell);
  fore.position.y = -0.03;

  const hand = group(`hand.${side}`, 0, -0.06, 0);
  const mitten = mesh(`Mitten.${side}`, new SphereGeometry(0.043, 24, 16), mats.shell);
  mitten.scale.set(1, 1.15, 0.85);
  mitten.position.y = -0.035;
  const thumb = mesh(`Thumb.${side}`, new SphereGeometry(0.018, 16, 12), mats.shell);
  thumb.position.set(-0.03 * sign, -0.022, 0.02);

  hand.add(mitten, thumb);
  elbow.add(fore, hand);
  shoulder.add(ball, upper, elbow);
  return shoulder;
}

function buildLeg(side: 'L' | 'R', mats: RobotMaterials): Group {
  const sign = side === 'L' ? 1 : -1;
  const thigh = group(`thigh.${side}`, 0.08 * sign, -0.01, 0);
  const thighMesh = mesh(`Thigh.${side}`, new CapsuleGeometry(0.05, 0.02, 6, 20), mats.shell);
  thighMesh.position.y = -0.02;
  thigh.add(thighMesh);
  const shin = group(`shin.${side}`, 0, -0.05, 0);
  const shinMesh = mesh(`Shin.${side}`, new CylinderGeometry(0.045, 0.05, 0.05, 24), mats.shell);
  shinMesh.position.y = -0.02;
  const foot = group(`foot.${side}`, 0, -0.05, 0);
  const boot = mesh(
    `Boot.${side}`,
    new RoundedBoxGeometry(0.12, 0.075, 0.17, 4, 0.034),
    mats.belly,
  );
  boot.position.set(0.006 * sign, -0.0225, 0.02);
  foot.add(boot);
  shin.add(shinMesh, foot);
  thigh.add(shin);
  return thigh;
}

function buildTorso(mats: RobotMaterials): Group {
  const spine = group('spine', 0, 0.02, 0);
  const bean = mesh('Body', new CapsuleGeometry(0.165, 0.06, 12, 32), mats.shell);
  bean.scale.set(1.04, 1, 0.85);
  bean.position.y = 0.13;
  const belly = mesh('BellyPanel', new SphereGeometry(1, 32, 24), mats.belly);
  belly.scale.set(0.1, 0.115, 0.035);
  belly.position.set(0, 0.1, 0.115);
  const chest = mesh('ChestLight', new SphereGeometry(0.02, 20, 14), mats.chestLight);
  chest.scale.z = 0.5;
  chest.position.set(0, 0.17, 0.14);
  spine.add(bean, belly, chest, buildHead(mats), buildArm('L', mats), buildArm('R', mats));
  return spine;
}

/** Build the placeholder robot. The returned group is the armature root ("root"). */
export function createPlaceholderRobot(): Group {
  const mats = createRobotMaterials();
  const root = group('root');
  const hips = group('hips', 0, 0.17, 0);
  hips.add(buildTorso(mats), buildLeg('L', mats), buildLeg('R', mats));
  root.add(hips);
  return root;
}

// A simple Alpha-Mini-like robot from three.js primitives, used only if alpha_mini.glb cannot be
// loaded. It follows the glb contract (+Y up, faces +Z, nodes head / shoulder.L / shoulder.R,
// meshes EyeL / EyeR with full-square UVs, EyeR mirrored) so everything else works unchanged;
// it has no clips, so all motions are procedural. The page labels it as a stand-in.
import {
  CapsuleGeometry,
  CircleGeometry,
  CylinderGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  SphereGeometry,
  type BufferGeometry,
} from 'three';

const shell = new MeshStandardMaterial({ name: 'StandInShell', color: 0xf4f6f7, roughness: 0.32 });
const joint = new MeshStandardMaterial({ name: 'StandInJoint', color: 0x9aa3aa, roughness: 0.45 });
const face = new MeshStandardMaterial({ name: 'StandInFace', color: 0x101417, roughness: 0.2 });
const eyeScreen = new MeshStandardMaterial({ name: 'EyeScreen', color: 0x080d0f });

/** Circle with UVs flipped to the glTF convention (v = 0 at the top), optionally mirrored. */
function eyeGeometry(radius: number, mirrored: boolean): BufferGeometry {
  const geometry = new CircleGeometry(radius, 48);
  const uv = geometry.getAttribute('uv');
  for (let i = 0; i < uv.count; i += 1) {
    const u = uv.getX(i);
    uv.setXY(i, mirrored ? 1 - u : u, 1 - uv.getY(i));
  }
  uv.needsUpdate = true;
  return geometry;
}

function mesh(geometry: BufferGeometry, material: MeshStandardMaterial, name = ''): Mesh {
  const m = new Mesh(geometry, material);
  m.name = name;
  return m;
}

function createArm(side: 1 | -1): Group {
  const shoulder = new Group();
  shoulder.name = side === 1 ? 'shoulder.L' : 'shoulder.R';
  shoulder.position.set(0.15 * side, 0.55, 0);
  shoulder.add(mesh(new SphereGeometry(0.045, 20, 14), joint));
  const arm = mesh(new CapsuleGeometry(0.036, 0.17, 6, 16), shell);
  arm.position.set(0.018 * side, -0.11, 0);
  arm.rotation.z = 0.12 * side;
  const hand = mesh(new SphereGeometry(0.034, 16, 12), joint);
  hand.position.set(0.04 * side, -0.23, 0.005);
  shoulder.add(arm, hand);
  return shoulder;
}

function createLeg(side: 1 | -1): Group {
  const leg = new Group();
  leg.position.set(0.06 * side, 0.3, 0);
  const thigh = mesh(new CapsuleGeometry(0.042, 0.13, 6, 16), shell);
  thigh.position.y = -0.09;
  const knee = mesh(new SphereGeometry(0.04, 16, 12), joint);
  knee.position.y = -0.18;
  const shin = mesh(new CapsuleGeometry(0.04, 0.08, 6, 16), shell);
  shin.position.y = -0.24;
  const foot = mesh(new CapsuleGeometry(0.035, 0.06, 6, 16), shell);
  foot.rotation.x = Math.PI / 2;
  foot.position.set(0, -0.295, 0.025);
  leg.add(thigh, knee, shin, foot);
  return leg;
}

function createHead(): Group {
  const head = new Group();
  head.name = 'head';
  head.position.set(0, 0.64, 0);
  const skull = mesh(new SphereGeometry(0.2, 40, 28), shell);
  skull.scale.set(1.05, 0.9, 0.95);
  skull.position.y = 0.17;
  const visor = mesh(new SphereGeometry(0.17, 40, 28, 0, Math.PI * 2, 0, Math.PI * 0.62), face);
  visor.rotation.x = Math.PI / 2;
  visor.scale.set(1, 0.62, 0.9);
  visor.position.set(0, 0.16, 0.06);
  const eyeL = mesh(eyeGeometry(0.045, false), eyeScreen, 'EyeL');
  eyeL.position.set(0.065, 0.175, 0.205);
  const eyeR = mesh(eyeGeometry(0.045, true), eyeScreen, 'EyeR');
  eyeR.position.set(-0.065, 0.175, 0.205);
  const tuft = mesh(new SphereGeometry(0.07, 20, 14), joint);
  tuft.scale.set(1.6, 0.5, 1.2);
  tuft.position.set(0, 0.34, -0.02);
  const neck = mesh(new CylinderGeometry(0.04, 0.05, 0.06, 20), joint);
  neck.position.y = -0.005;
  head.add(skull, visor, eyeL, eyeR, tuft, neck);
  return head;
}

export function createStandInRobot(): Group {
  const robot = new Group();
  robot.name = 'AlphaMiniStandIn';
  const torso = mesh(new CapsuleGeometry(0.13, 0.12, 8, 24), shell);
  torso.scale.set(1, 1, 0.78);
  torso.position.y = 0.46;
  const belt = mesh(new CylinderGeometry(0.115, 0.115, 0.03, 32), joint);
  belt.position.y = 0.33;
  const badge = mesh(
    new CircleGeometry(0.02, 24),
    new MeshStandardMaterial({
      name: 'PipiBlueGlow',
      color: 0x2a7fff,
      emissive: 0x2a7fff,
      emissiveIntensity: 0.6,
    }),
  );
  badge.position.set(0.05, 0.5, 0.103);
  robot.add(
    torso,
    belt,
    badge,
    createHead(),
    createArm(1),
    createArm(-1),
    createLeg(1),
    createLeg(-1),
  );
  return robot;
}

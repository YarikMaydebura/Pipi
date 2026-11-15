// The 3D Pipi: owns the render loop and combines eyes, clips, procedural motion, idle life and
// cursor-following every frame. Any runtime failure calls onFatal so main.ts can switch to the
// 2D fallback — the pet must never go blank.
import { Mesh, Raycaster, Vector2, Vector3, type Material } from 'three';
import type { EyeState } from '@pipi/shared';
import { EyeController } from '../eyes/eyeController';
import { EyeTextures } from '../eyes/eyeTextures';
import { clamp } from '../eyes/eyeFrame';
import { applySpeechLevel } from '../eyes/speechGlow';
import { idlePose, lookAt, NO_LOOK, type LookTarget, type ScreenPoint } from '../motion/idle';
import { MotionPlayer } from '../motion/motions';
import { MouthController } from '../mouth/mouthController';
import type { MouthShape } from '../mouth/mouthShapes';
import { MouthTexture } from '../mouth/mouthTexture';
import { addPoses, damp, dampTravel, pose, ZERO_POSE } from '../motion/pose';
import type { FaceFlash, PetView } from '../pet/PetView';
import { ClipPlayer } from './clipPlayer';
import { cheekModeFor, GlowParts } from './glowParts';
import { loadRobot, type LoadedRobot } from './loadRobot';
import { buildRig, RigPoser, type RobotRig } from './robotRig';
import { createStage, MAX_PIXEL_RATIO, type Stage } from './stage';

export interface Pet3DOptions {
  readonly reducedMotion: boolean;
  /** Called once if rendering breaks (context lost, exception in the loop). */
  readonly onFatal: (error: unknown) => void;
}

const LOOK_RATE = 5; // how fast the head follows the cursor (1/s)
const MAX_FRAME_DT = 0.1;
const REDUCED_TRAVEL = 0.3;
const EYE_LEVEL_ABOVE_NECK = 0.22; // in robot heights, used to aim the look-at
const SPEECH_HEAD_LIFT = -0.07; // head tips up a little on loud syllables (radians per level)
const SPEECH_BODY_LIFT = 0.008;

const seconds = (): number => performance.now() / 1000;

class Pet3DView implements PetView {
  readonly kind = '3d' as const;
  private readonly eyes = new EyeController(seconds());
  private readonly eyeTextures = new EyeTextures();
  private readonly mouth = new MouthController();
  private readonly mouthTexture = new MouthTexture();
  private readonly motions = new MotionPlayer();
  private readonly raycaster = new Raycaster();
  private readonly rig: RobotRig;
  private readonly poser: RigPoser;
  private readonly glow: GlowParts;
  private readonly clips: ClipPlayer | null;
  private cursor: ScreenPoint | null = null;
  private look: LookTarget = NO_LOOK;
  private reducedMotion: boolean;
  private lastTime = seconds();
  private pixelRatio = 0;
  private failed = false;
  private speechLevel = 0;
  private cheekFlashUntil = 0;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly stage: Stage,
    robot: LoadedRobot,
    private readonly options: Pet3DOptions,
  ) {
    this.reducedMotion = options.reducedMotion;
    this.rig = buildRig(robot.model, {
      left: this.eyeTextures.left.material,
      right: this.eyeTextures.right.material,
      mouth: this.mouthTexture.material,
    });
    stage.scene.add(this.rig.poseRoot);
    this.poser = new RigPoser(this.rig);
    this.glow = new GlowParts(robot.model);
    this.clips = robot.clips.length > 0 ? new ClipPlayer(robot.model, robot.clips) : null;

    canvas.addEventListener('webglcontextlost', this.onContextLost);
    stage.renderer.setAnimationLoop(this.onFrame);
    console.info(`[pipi] 3D pet ready (${robot.source} model, ${robot.clips.length} clips)`);
  }

  setEyeState(state: EyeState): void {
    this.eyes.setState(state, seconds());
  }

  playMotion(name: string): boolean {
    const now = seconds();
    if (this.clips?.play(name)) {
      this.motions.stop(now);
      this.mouth.onMotion(name, now);
      return true;
    }
    const known = this.motions.play(name, now);
    if (known) this.mouth.onMotion(name, now);
    return known;
  }

  setBaseMotion(name: string, interrupt: boolean): boolean {
    const now = seconds();
    // A clip loop wins; without one, the procedural loop plays on top of the idle clip.
    if (this.clips?.setBase(name, interrupt)) {
      this.motions.setBase('idle', now, interrupt);
      return true;
    }
    if (!this.motions.setBase(name, now, interrupt)) return false;
    this.clips?.setBase('idle', interrupt);
    return true;
  }

  flashFace(face: FaceFlash | null): void {
    const now = seconds();
    if (!face) {
      this.eyes.clearFlash();
      this.mouth.flash(null, now);
      this.cheekFlashUntil = 0;
      return;
    }
    const until = now + face.durationMs / 1000;
    if (face.eyes) this.eyes.flash(face.eyes, now, face.durationMs / 1000);
    this.mouth.flash(face.mouth ?? null, until);
    this.cheekFlashUntil = face.cheeks ? until : 0;
  }

  setMouthOverride(shape: MouthShape | null): void {
    this.mouth.setOverride(shape);
  }

  setCursor(point: ScreenPoint | null): void {
    this.cursor = point;
  }

  hitTest(point: ScreenPoint): boolean {
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    if (width === 0 || height === 0) return false;
    const ndc = new Vector2((point.x / width) * 2 - 1, -(point.y / height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.stage.camera);
    return this.raycaster.intersectObject(this.rig.poseRoot, true).length > 0;
  }

  setCheeks(on: boolean): void {
    this.glow.setCheeks(on);
  }

  setChestPulse(on: boolean): void {
    this.glow.setChestPulse(on);
  }

  setSpeechLevel(level: number): void {
    this.speechLevel = clamp(level, 0, 1);
    this.glow.setSpeechLevel(this.speechLevel);
  }

  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced;
  }

  dispose(): void {
    this.failed = true;
    this.stage.renderer.setAnimationLoop(null);
    this.canvas.removeEventListener('webglcontextlost', this.onContextLost);
    this.clips?.dispose();
    this.eyeTextures.dispose();
    this.mouthTexture.dispose();
    const materials = new Set<Material>();
    this.rig.poseRoot.traverse((object) => {
      if (!(object instanceof Mesh)) return;
      object.geometry.dispose();
      for (const m of Array.isArray(object.material) ? object.material : [object.material]) {
        materials.add(m);
      }
    });
    for (const m of materials) m.dispose();
    this.stage.dispose();
  }

  private readonly onContextLost = (event: Event): void => {
    event.preventDefault();
    this.fail(new Error('WebGL context lost'));
  };

  private readonly onFrame = (timeMs: number): void => {
    if (this.failed) return;
    try {
      this.renderFrame(timeMs / 1000);
    } catch (error: unknown) {
      this.fail(error);
    }
  };

  private fail(error: unknown): void {
    if (this.failed) return;
    this.failed = true;
    this.stage.renderer.setAnimationLoop(null);
    this.options.onFatal(error);
  }

  /** Where the eyes are on screen (CSS px), so the head can turn toward the cursor. */
  private headScreenPosition(): ScreenPoint {
    const position = new Vector3(0, 0.7, 0);
    const head = this.rig.bones.head;
    if (head) {
      head.getWorldPosition(position);
      position.y += EYE_LEVEL_ABOVE_NECK;
    }
    position.project(this.stage.camera);
    return {
      x: ((position.x + 1) / 2) * this.canvas.clientWidth,
      y: ((1 - position.y) / 2) * this.canvas.clientHeight,
    };
  }

  private updateLook(dt: number): number {
    const target = lookAt(this.cursor, this.headScreenPosition());
    const headTarget = this.reducedMotion ? { ...target, yaw: 0, pitch: 0 } : target;
    const previousYaw = this.look.yaw;
    this.look = {
      yaw: damp(this.look.yaw, headTarget.yaw, LOOK_RATE, dt),
      pitch: damp(this.look.pitch, headTarget.pitch, LOOK_RATE, dt),
      gazeX: damp(this.look.gazeX, target.gazeX, LOOK_RATE * 2, dt),
      gazeY: damp(this.look.gazeY, target.gazeY, LOOK_RATE * 2, dt),
    };
    // Angular speed of the head; the antenna lags behind it like a little spring.
    return dt > 0 ? (this.look.yaw - previousYaw) / dt : 0;
  }

  private renderFrame(now: number): void {
    const dt = clamp(now - this.lastTime, 0, MAX_FRAME_DT);
    this.lastTime = now;
    const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
    if (ratio !== this.pixelRatio) {
      this.pixelRatio = ratio;
      this.stage.resize();
    }

    const yawSpeed = this.updateLook(dt);
    this.poser.resetToRest();
    this.clips?.update(dt);

    const hasIdleClip = this.clips?.has('idle') ?? false;
    let total = addPoses(
      hasIdleClip ? ZERO_POSE : idlePose(now, this.reducedMotion),
      this.motions.sample(now),
      pose({
        headYaw: this.look.yaw,
        headPitch: this.look.pitch,
        antennaRoll: clamp(-yawSpeed * 0.12, -0.35, 0.35),
      }),
      pose({
        headPitch: SPEECH_HEAD_LIFT * this.speechLevel,
        bodyLift: SPEECH_BODY_LIFT * this.speechLevel,
      }),
    );
    if (this.reducedMotion) total = dampTravel(total, REDUCED_TRAVEL);
    this.poser.apply(total);

    // The contact shadow shrinks and fades while Pipi is in the air.
    const air = clamp(total.bodyLift * 4, 0, 0.6);
    this.stage.shadow.scale.setScalar(1 - air * 0.5);

    const eyeFrame = applySpeechLevel(
      this.eyes.frame(now, { x: this.look.gazeX, y: this.look.gazeY }),
      this.speechLevel,
    );
    this.eyeTextures.draw(eyeFrame);
    const faceState = this.eyes.visibleState(now);
    this.mouthTexture.draw(this.mouth.frame(faceState, this.speechLevel, now));
    const cheekFlash = now < this.cheekFlashUntil && faceState !== 'off';
    this.glow.update(now, dt, cheekFlash ? 'bright' : cheekModeFor(faceState));

    this.stage.renderer.render(this.stage.scene, this.stage.camera);
  }
}

/** Create the 3D pet. Throws if WebGL or the model cannot be set up (caller falls back). */
export async function create3DView(
  canvas: HTMLCanvasElement,
  options: Pet3DOptions,
): Promise<PetView> {
  const stage = createStage(canvas);
  try {
    const robot = await loadRobot();
    return new Pet3DView(canvas, stage, robot, options);
  } catch (error: unknown) {
    stage.dispose();
    throw error;
  }
}

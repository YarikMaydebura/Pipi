// The 3D fake robot: owns the render loop and combines eye displays, clips, procedural motions,
// speech glow and a slow camera drift every frame. Implements RobotView for the controller.
// Any runtime failure (WebGL context lost, exception in the loop) calls onFatal once, so
// main.ts can switch to the 2D fallback — the robot must never go blank during a demo.
import type { EyeState } from '@pipi/shared';
import { applySpeechLevel, clamp, EyeController } from '@pipi/shared/look';
import type { MeshStandardMaterial } from 'three';
import { baseFadeSeconds, loopGestureSeconds, planMotion, type BaseLoop } from '../motionPlan';
import {
  addPoses,
  PROCEDURAL_MOTIONS,
  REST,
  sampleMotion,
  scalePose,
  type RobotPose,
} from '../proceduralMotions';
import type { MotionHandle, RobotView } from '../robotController';
import { ClipDirector } from './clipDirector';
import { EyeDisplays } from './eyeDisplays';
import { loadModel, type ModelSource } from './loadModel';
import { buildRig, RigPoser, type Rig } from './rig';
import { createStage, type Stage } from './stage';

export interface RobotSceneOptions {
  readonly reducedMotion: boolean;
  readonly onFatal: (error: unknown) => void;
}

const MAX_FRAME_DT = 0.1;
const REDUCED_TRAVEL = 0.3; // prefers-reduced-motion: procedural motions keep 30 % of travel
const GESTURE_EDGE_S = 0.3; // procedural gestures fade in / out over this long
const SPEECH_HEAD_LIFT = -0.05; // head tips up a little on loud syllables (radians per level)
const BADGE_BOOST = 2.5;

const seconds = (): number => performance.now() / 1000;

interface ProceduralGesture {
  readonly name: string;
  readonly start: number;
  readonly durationS: number;
  readonly resolve: () => void;
}

interface BaseState {
  readonly loop: BaseLoop;
  readonly since: number;
}

/** 0..1 envelope: eases in at the start and out at the end of a gesture. */
function envelope(elapsed: number, duration: number): number {
  const edge = Math.min(GESTURE_EDGE_S, duration / 3);
  const into = clamp(elapsed / edge, 0, 1);
  const out = clamp((duration - elapsed) / edge, 0, 1);
  return Math.sin((Math.min(into, out) * Math.PI) / 2);
}

class RobotScene implements RobotView {
  readonly source: ModelSource;
  private readonly eyes = new EyeController(seconds());
  private readonly displays = new EyeDisplays();
  private readonly rig: Rig;
  private readonly poser: RigPoser;
  private readonly clips: ClipDirector | null;
  private readonly badgeBase: number[];
  private base: BaseState = { loop: 'idle', since: 0 };
  private previousBase: BaseState = { loop: 'idle', since: 0 };
  private gesture: ProceduralGesture | null = null;
  private speechLevel = 0;
  private reducedMotion: boolean;
  private lastTime = seconds();
  private failed = false;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly stage: Stage,
    loaded: Awaited<ReturnType<typeof loadModel>>,
    private readonly options: RobotSceneOptions,
  ) {
    this.source = loaded.source;
    this.reducedMotion = options.reducedMotion;
    this.rig = buildRig(loaded.model, {
      left: this.displays.left.material,
      right: this.displays.right.material,
    });
    stage.scene.add(this.rig.root);
    this.poser = new RigPoser(this.rig);
    this.clips = loaded.clips.length > 0 ? new ClipDirector(loaded.model, loaded.clips) : null;
    this.badgeBase = this.rig.badge.map((m) => m.emissiveIntensity);
    canvas.addEventListener('webglcontextlost', this.onContextLost);
    window.addEventListener('resize', this.onResize);
    stage.renderer.setAnimationLoop(this.onFrame);
    console.info(`[fake robot] 3D robot ready (${loaded.source}, ${loaded.clips.length} clips)`);
  }

  // --- RobotView -------------------------------------------------------------------------------

  setEyes(state: EyeState): void {
    this.eyes.setState(state, seconds());
  }

  setSpeechLevel(level: number): void {
    this.speechLevel = clamp(level, 0, 1);
  }

  setBase(loop: BaseLoop, interrupt: boolean): void {
    if (this.clips?.setBase(loop, interrupt)) {
      if (interrupt) this.endGesture();
      return;
    }
    // No clip for this loop: blend between procedural base poses instead.
    if (interrupt) this.endGesture();
    this.previousBase = this.base;
    this.base = { loop, since: seconds() };
  }

  perform(name: string): MotionHandle | null {
    const plan = planMotion(name, (clip) => this.clips?.has(clip) ?? false);
    if (plan.kind === 'unknown') return null;
    if (plan.kind === 'clip' && this.clips) {
      const finished = this.clips.play(plan.clip, loopGestureSeconds(plan.clip));
      if (finished) {
        this.endGesture();
        return { finished };
      }
    }
    const procedural = plan.kind === 'procedural' ? plan.name : name;
    const def = PROCEDURAL_MOTIONS[procedural];
    if (!def) return null;
    this.endGesture();
    const durationS = def.loop ? loopGestureSeconds(procedural) : def.durationS;
    const finished = new Promise<void>((resolve) => {
      this.gesture = { name: procedural, start: seconds(), durationS, resolve };
    });
    return { finished };
  }

  // --- page integration ------------------------------------------------------------------------

  setReducedMotion(on: boolean): void {
    this.reducedMotion = on;
  }

  dispose(): void {
    this.stage.renderer.setAnimationLoop(null);
    this.canvas.removeEventListener('webglcontextlost', this.onContextLost);
    window.removeEventListener('resize', this.onResize);
    this.endGesture();
    this.clips?.dispose();
    this.displays.dispose();
    this.stage.dispose();
  }

  // --- frame -----------------------------------------------------------------------------------

  private endGesture(): void {
    this.gesture?.resolve();
    this.gesture = null;
  }

  /** Procedural base loop (only when the model has no clip for it), crossfaded. */
  private basePose(t: number): RobotPose {
    if (this.clips?.has(this.base.loop)) return REST;
    const current = sampleMotion(this.base.loop, t - this.base.since);
    const fade = baseFadeSeconds(this.base.loop);
    const w = clamp((t - this.base.since) / fade, 0, 1);
    if (w >= 1 || this.clips?.has(this.previousBase.loop)) return current;
    const previous = sampleMotion(this.previousBase.loop, t - this.previousBase.since);
    const eased = w * w * (3 - 2 * w);
    return addPoses(scalePose(previous, 1 - eased), scalePose(current, eased));
  }

  private gesturePose(t: number): RobotPose {
    const gesture = this.gesture;
    if (!gesture) return REST;
    const elapsed = t - gesture.start;
    if (elapsed >= gesture.durationS) {
      this.endGesture();
      return REST;
    }
    return scalePose(sampleMotion(gesture.name, elapsed), envelope(elapsed, gesture.durationS));
  }

  private gaze(t: number): { x: number; y: number } {
    if (this.reducedMotion) return { x: 0, y: 0 };
    return {
      x: 0.22 * Math.sin(t * 0.31) + 0.08 * Math.sin(t * 1.13),
      y: 0.1 * Math.sin(t * 0.23 + 1.7),
    };
  }

  private readonly onFrame = (): void => {
    if (this.failed) return;
    try {
      const t = seconds();
      const dt = Math.min(MAX_FRAME_DT, Math.max(0, t - this.lastTime));
      this.lastTime = t;

      this.poser.resetToRest();
      this.clips?.update(dt);
      let pose = addPoses(this.basePose(t), this.gesturePose(t));
      if (this.reducedMotion) pose = scalePose(pose, REDUCED_TRAVEL);
      pose = { ...pose, headPitch: pose.headPitch + SPEECH_HEAD_LIFT * this.speechLevel };
      this.poser.apply(pose);

      const frame = this.eyes.frame(t, this.gaze(t), true);
      this.displays.draw(applySpeechLevel(frame, this.speechLevel));
      this.rig.badge.forEach((material: MeshStandardMaterial, i) => {
        material.emissiveIntensity =
          (this.badgeBase[i] ?? 1) * (1 + BADGE_BOOST * this.speechLevel);
      });

      this.stage.drift(t, this.reducedMotion ? 0 : 1);
      this.stage.renderer.render(this.stage.scene, this.stage.camera);
    } catch (error: unknown) {
      this.fail(error);
    }
  };

  private readonly onResize = (): void => this.stage.resize();

  private readonly onContextLost = (event: Event): void => {
    event.preventDefault();
    this.fail(new Error('WebGL context lost'));
  };

  private fail(error: unknown): void {
    if (this.failed) return;
    this.failed = true;
    this.stage.renderer.setAnimationLoop(null);
    this.options.onFatal(error);
  }
}

export type { RobotScene };

/** Build the 3D robot; throws if WebGL is unavailable (the caller shows the 2D fallback). */
export async function createRobotScene(
  canvas: HTMLCanvasElement,
  options: RobotSceneOptions,
): Promise<RobotScene> {
  const stage = createStage(canvas);
  const loaded = await loadModel(window.location.href);
  return new RobotScene(canvas, stage, loaded, options);
}

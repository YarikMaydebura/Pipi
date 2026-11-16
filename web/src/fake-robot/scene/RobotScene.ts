// The 3D fake robot: owns the render loop and combines eye displays, clips, procedural motions,
// speech glow, the duel signal cue and a slow camera drift every frame. Implements RobotView for
// the controller.
// Any runtime failure (WebGL context lost, exception in the loop) calls onFatal once, so
// main.ts can switch to the 2D fallback — the robot must never go blank during a demo.
import type { EyeState } from '@pipi/shared';
import { applySpeechLevel, clamp, EyeController } from '@pipi/shared/look';
import type { MeshStandardMaterial } from 'three';
import { cueForEyes, cueLook, CUE_COLORS, type DuelCue } from '../duelCue';
import {
  baseFadeSeconds,
  motionSeconds,
  planMotion,
  type BaseLoop,
  type MotionMode,
} from '../motionPlan';
import { PROCEDURAL_MOTIONS, sampleMotion } from '../proceduralMotions';
import type { MotionHandle, RobotView } from '../robotController';
import { addPoses, REST, scalePose, smoothstep, type RobotPose } from '../robotPose';
import { ClipDirector } from './clipDirector';
import { EyeDisplays } from './eyeDisplays';
import { loadModel, type ModelSource } from './loadModel';
import { buildRig, RigPoser, type Rig } from './rig';
import { createStage, type Stage } from './stage';

export interface RobotSceneOptions {
  readonly reducedMotion: boolean;
  /** false = ignore the model's clips, so every motion is its procedural fallback (?clips=0). */
  readonly useClips: boolean;
  readonly onFatal: (error: unknown) => void;
}

const MAX_FRAME_DT = 0.1;
const REDUCED_TRAVEL = 0.3; // prefers-reduced-motion: procedural motions keep 30 % of travel
const GESTURE_EDGE_S = 0.3; // procedural gestures fade in / out over this long
const SPEECH_HEAD_LIFT = -0.05; // head tips up a little on loud syllables (radians per level)
const BADGE_BOOST = 2.5;
const CUE_RATE = 14; // how fast the signal cue follows its target (1/s): quick, never a hard cut
const CUE_EYE_BOOST = 0.6; // the eye displays glow this much brighter at full cue strength

const seconds = (): number => performance.now() / 1000;

interface ProceduralGesture {
  readonly name: string;
  readonly mode: MotionMode;
  readonly start: number;
  /** When it ends by itself (one-shot length, timed loop, or the held safety cap). */
  endsAt: number;
  readonly attackS: number;
  readonly finished: Promise<void>;
  readonly resolve: () => void;
}

/** The pose a replaced gesture left behind; it fades out so nothing snaps. */
interface FadingPose {
  readonly pose: RobotPose;
  readonly at: number;
}

interface BaseState {
  readonly loop: BaseLoop;
  readonly since: number;
}

/** 0..1 envelope: eases in over the gesture's attack and out before its own end. */
function envelope(gesture: ProceduralGesture, t: number): number {
  const duration = gesture.endsAt - gesture.start;
  const into = clamp((t - gesture.start) / Math.min(gesture.attackS, duration / 3), 0, 1);
  const out = clamp((gesture.endsAt - t) / Math.min(GESTURE_EDGE_S, duration / 3), 0, 1);
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
  private fading: FadingPose | null = null;
  private gestureNow: RobotPose = REST; // what the gesture layer showed in the last frame
  private cue: DuelCue = 'none';
  private cueSince = 0;
  private cueColor: string = CUE_COLORS.countdown;
  private cueStrength = 0;
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
    const clips = options.useClips ? loaded.clips : [];
    this.clips = clips.length > 0 ? new ClipDirector(loaded.model, clips) : null;
    this.badgeBase = this.rig.badge.map((m) => m.emissiveIntensity);
    canvas.addEventListener('webglcontextlost', this.onContextLost);
    window.addEventListener('resize', this.onResize);
    stage.renderer.setAnimationLoop(this.onFrame);
    console.info(`[fake robot] 3D robot ready (${loaded.source}, ${clips.length} clips in use)`);
  }

  // --- RobotView -------------------------------------------------------------------------------

  setEyes(state: EyeState): void {
    const now = seconds();
    this.eyes.setState(state, now);
    // The duel signals also tint the scene (blink is a one-shot: the requested state stays).
    const cue = cueForEyes(this.eyes.requestedState());
    if (cue === this.cue) return;
    this.cue = cue;
    this.cueSince = now;
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
    if (plan.kind === 'clip') {
      const request = { mode: plan.mode, seconds: motionSeconds(plan.clip, plan.mode) };
      const finished = this.clips?.play(plan.clip, request);
      if (!finished) return null;
      this.endGesture();
      return { finished };
    }
    const def = PROCEDURAL_MOTIONS[plan.name];
    if (!def) return null;
    const now = seconds();
    const lastsS = plan.mode === 'once' ? def.durationS : motionSeconds(plan.name, plan.mode);
    const current = this.gesture;
    if (current && current.name === plan.name && current.mode === 'held' && plan.mode === 'held') {
      current.endsAt = now + lastsS; // re-sent while acting: keep going, no restart
      return { finished: current.finished };
    }
    this.endGesture();
    this.clips?.endMotion(); // a clip motion that was still playing gives way
    let resolve = (): void => undefined;
    const finished = new Promise<void>((done) => {
      resolve = done;
    });
    this.gesture = {
      name: plan.name,
      mode: plan.mode,
      start: now,
      endsAt: now + lastsS,
      attackS: def.attackS ?? GESTURE_EDGE_S,
      finished,
      resolve,
    };
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

  /** End the procedural gesture; what it showed last fades out instead of snapping to rest. */
  private endGesture(): void {
    if (!this.gesture) return;
    this.gesture.resolve();
    this.gesture = null;
    this.fading = { pose: this.gestureNow, at: seconds() };
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

  /** The gesture layer: the running procedural motion plus the fading rest of the previous one. */
  private gesturePose(t: number): RobotPose {
    let total = REST;
    if (this.fading) {
      const left = 1 - smoothstep((t - this.fading.at) / GESTURE_EDGE_S);
      if (left <= 0) this.fading = null;
      else total = scalePose(this.fading.pose, left);
    }
    const gesture = this.gesture;
    if (gesture && t >= gesture.endsAt) {
      // Ended by itself, already eased out by the envelope: nothing is left to fade.
      gesture.resolve();
      this.gesture = null;
    } else if (gesture) {
      const sampled = sampleMotion(gesture.name, t - gesture.start);
      total = addPoses(total, scalePose(sampled, envelope(gesture, t)));
    }
    this.gestureNow = total;
    return total;
  }

  /** Tint light, desk ring and eye glow for the duel signals (countdown amber, go green). */
  private updateCue(t: number, dt: number): void {
    const look = cueLook(this.cue, {
      t,
      sinceS: t - this.cueSince,
      reducedMotion: this.reducedMotion,
    });
    if (look.color !== null) this.cueColor = look.color;
    // A new signal shows at once (the "go" must not lag); it only fades OUT softly.
    this.cueStrength =
      look.strength >= this.cueStrength
        ? look.strength
        : look.strength + (this.cueStrength - look.strength) * Math.exp(-CUE_RATE * dt);
    this.stage.setCue(this.cueColor, this.cueStrength);
    this.displays.setBoost(CUE_EYE_BOOST * this.cueStrength);
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

      this.updateCue(t, dt);
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

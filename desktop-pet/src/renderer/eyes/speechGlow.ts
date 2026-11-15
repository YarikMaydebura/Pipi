// While Pipi speaks, its eyes glow brighter and stretch a tiny bit with the voice's loudness.
import { clamp, type EyeFrame } from './eyeFrame';

const GLOW_BOOST = 0.35;
const HEIGHT_BOOST = 0.06;

/** `level` 0..1 from the speech audio (0 = silent: the frame is returned unchanged). */
export function applySpeechLevel(frame: EyeFrame, level: number): EyeFrame {
  const l = clamp(level, 0, 1);
  if (l === 0 || frame.shape === 'off') return frame;
  return {
    ...frame,
    glow: Math.min(1, frame.glow + GLOW_BOOST * l),
    height: frame.height * (1 + HEIGHT_BOOST * l),
  };
}

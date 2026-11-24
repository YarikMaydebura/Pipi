// Mouse handling for a click-through window:
// - every cursor position (from main's feed or forwarded mouse-moves) is hit-tested against
//   Pipi; main only lets clicks through where Pipi is NOT,
// - pressing on Pipi and moving drags the window; a press without moving is a "poke",
// - the handlers hear about pokes, drags starting/ending and the cursor entering/leaving Pipi
//   (interaction/ turns these into reactions),
// - `isOverControls` names other clickable things (the persona cards): the window catches the
//   mouse there too, but they are not Pipi (no hover reaction, no poke, no drag).
import type { PetBridge } from '../../preload/bridge';
import type { ScreenPoint } from '../motion/idle';
import type { PetView } from '../pet/PetView';

const DRAG_THRESHOLD_PX = 4;

export interface PointerHandlers {
  readonly onPoke: () => void;
  readonly onDrag?: (dragging: boolean) => void;
  readonly onHover?: (over: boolean) => void;
}

function isPoint(value: unknown): value is ScreenPoint {
  if (typeof value !== 'object' || value === null) return false;
  const { x, y } = value as { x?: unknown; y?: unknown };
  return typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y);
}

export function wirePointerInput(
  getView: () => PetView,
  bridge: PetBridge | undefined,
  handlers: PointerHandlers,
  isOverControls: (point: ScreenPoint) => boolean = () => false,
): () => void {
  let interactive = false;
  let hovering = false;
  let press: { screenX: number; screenY: number; moved: boolean } | null = null;

  const setInteractive = (value: boolean): void => {
    if (value === interactive) return;
    interactive = value;
    bridge?.setInteractive(value);
  };

  const setHovering = (value: boolean): void => {
    if (value === hovering) return;
    hovering = value;
    handlers.onHover?.(value);
    document.body.classList.toggle('is-over-pet', value);
  };

  const track = (point: ScreenPoint): void => {
    getView().setCursor(point);
    if (press) return;
    const overPet = getView().hitTest(point);
    setHovering(overPet);
    setInteractive(overPet || isOverControls(point));
  };

  const onMouseMove = (event: MouseEvent): void => {
    track({ x: event.clientX, y: event.clientY });
    if (!press) return;
    const distance = Math.hypot(event.screenX - press.screenX, event.screenY - press.screenY);
    if (!press.moved && distance > DRAG_THRESHOLD_PX) {
      press.moved = true;
      document.body.classList.add('is-dragging');
      bridge?.drag('start');
      handlers.onDrag?.(true);
    }
  };

  const onPointerDown = (event: PointerEvent): void => {
    if (event.button !== 0) return;
    if (!getView().hitTest({ x: event.clientX, y: event.clientY })) return;
    press = { screenX: event.screenX, screenY: event.screenY, moved: false };
  };

  const endPress = (allowPoke: boolean): void => {
    if (!press) return;
    const moved = press.moved;
    press = null;
    if (moved) {
      bridge?.drag('end');
      handlers.onDrag?.(false);
    } else if (allowPoke) handlers.onPoke();
    document.body.classList.remove('is-dragging');
  };

  const onPointerUp = (event: PointerEvent): void => {
    endPress(true);
    track({ x: event.clientX, y: event.clientY });
  };
  const onBlur = (): void => endPress(false);

  const unsubscribe = bridge?.onCursor((point) => {
    if (isPoint(point)) track(point);
  });
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointerup', onPointerUp);
  window.addEventListener('pointercancel', onBlur);
  window.addEventListener('blur', onBlur);

  return () => {
    unsubscribe?.();
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('pointerdown', onPointerDown);
    window.removeEventListener('pointerup', onPointerUp);
    window.removeEventListener('pointercancel', onBlur);
    window.removeEventListener('blur', onBlur);
  };
}

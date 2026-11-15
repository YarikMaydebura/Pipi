// The 2D fallback's mouth: one inline SVG path (shapes from mouth/mouthSvg.ts) with the eyes'
// teal gradient. Built with DOM calls only (no innerHTML). Looks are in style.css.
import { PALETTES } from '../eyes/eyeFrame';
import { sameMouthFrame, type MouthFrame } from '../mouth/mouthFrame';
import { GRADIENT_BAND } from '../mouth/mouthShapes';
import { mouthSvgPath } from '../mouth/mouthSvg';

const SVG_NS = 'http://www.w3.org/2000/svg';
const VIEW = 100;
const GRADIENT_ID = 'pipi-fallback-mouth-teal';

function svgElement(name: string, attributes: Record<string, string>): SVGElement {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function tealGradient(): SVGElement {
  const gradient = svgElement('linearGradient', {
    id: GRADIENT_ID,
    gradientUnits: 'userSpaceOnUse',
    x1: '0',
    y1: String(GRADIENT_BAND.top * VIEW),
    x2: '0',
    y2: String(GRADIENT_BAND.bottom * VIEW),
  });
  const stops: [string, string][] = [
    ['0', PALETTES.teal.light],
    ['0.5', PALETTES.teal.mid],
    ['1', PALETTES.teal.deep],
  ];
  for (const [offset, color] of stops) {
    gradient.append(svgElement('stop', { offset, 'stop-color': color }));
  }
  return gradient;
}

export interface FallbackMouth {
  show(frame: MouthFrame): void;
}

export function createFallbackMouth(face: HTMLElement): FallbackMouth {
  const svg = svgElement('svg', {
    class: 'fallback-mouth',
    viewBox: `0 0 ${VIEW} ${VIEW}`,
    'aria-hidden': 'true',
  });
  const defs = svgElement('defs', {});
  defs.append(tealGradient());
  const path = svgElement('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
  svg.append(defs, path);
  face.querySelector('.fallback-mouth')?.remove(); // a second fallback view replaces the first
  face.append(svg);

  let last: MouthFrame | null = null;
  return {
    show(frame) {
      if (sameMouthFrame(last, frame)) return;
      last = frame;
      const shape = mouthSvgPath(frame, VIEW);
      const paint = `url(#${GRADIENT_ID})`;
      path.setAttribute('d', shape.d);
      path.setAttribute('fill', shape.filled ? paint : 'none');
      path.setAttribute('stroke', shape.filled ? 'none' : paint);
      path.setAttribute('stroke-width', String(shape.strokeWidth));
      svg.setAttribute('data-shape', frame.shape);
    },
  };
}

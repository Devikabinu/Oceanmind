export type RGB = [number, number, number];

// Sequential (SST): deep blue -> cyan -> green -> yellow -> orange -> red
const SEQUENTIAL: RGB[] = [
  [49, 54, 149],
  [69, 117, 180],
  [116, 173, 209],
  [171, 217, 233],
  [254, 224, 144],
  [253, 174, 97],
  [244, 109, 67],
  [215, 48, 39],
  [165, 0, 38],
];

// Diverging (anomaly / error): blue -> near white -> red, centred on 0
const DIVERGING: RGB[] = [
  [33, 102, 172],
  [103, 169, 207],
  [209, 229, 240],
  [247, 247, 247],
  [253, 219, 199],
  [239, 138, 98],
  [178, 24, 43],
];

function sample(stops: RGB[], t: number): RGB {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const a = stops[i];
  const b = stops[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

export interface Scale {
  min: number;
  max: number;
  diverging: boolean;
  color: (v: number) => RGB;
}

/** Sequential scale over [min,max], or a symmetric diverging scale around 0 using max(|min|,|max|). */
export function makeScale(min: number, max: number, diverging: boolean): Scale {
  if (diverging) {
    const m = Math.max(Math.abs(min), Math.abs(max), 0.5);
    return { min: -m, max: m, diverging, color: (v) => sample(DIVERGING, (v + m) / (2 * m)) };
  }
  const span = max - min || 1;
  return { min, max, diverging, color: (v) => sample(SEQUENTIAL, (v - min) / span) };
}

export function cssGradient(scale: Scale, steps = 12): string {
  const parts: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const [r, g, b] = scale.color(scale.min + ((scale.max - scale.min) * i) / steps);
    parts.push(`rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`);
  }
  return `linear-gradient(to right, ${parts.join(",")})`;
}

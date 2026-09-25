export type Tone = "history" | "future" | "range";
export type Layer = { id: string; label: string; history: number[]; future: number[] };
export type Point3 = { x: number; y: number; z: number };
export type Point2 = { x: number; y: number; depth: number };
export type Prism = {
  key: string;
  row: number;
  step: number;
  horizon: number;
  tone: Tone;
  x: number;
  z: number;
  width: number;
  depth: number;
  height: number;
  shellFloor: number;
  cameraDepth: number;
};
export type Guide = { key: string; x1: number; y1: number; x2: number; y2: number };
export type Label = { key: string; x: number; y: number; text: string; anchor: "start" | "middle" | "end" };
export type Boundary = Omit<Guide, "key">;
export type Band = { key: string; x: number; y1: number; y2: number; width: number };
export type Column = { step: number; bands: Band[] };
export type Scape = {
  viewBox: string;
  width: number;
  height: number;
  prisms: Prism[];
  guides: Guide[];
  labels: Label[];
  rowLabels: Label[];
  boundary: Boundary;
  columns: Column[];
  ground: string;
  rows: number;
  steps: number;
  historyLength: number;
  futureLength: number;
};

export const RANGE_GROWTH = 0.055;
export const LONGEST_ROW_NAME = 12;
const SPAN = 880;
const ROW_GAP = 145;
const PLOT_HEIGHT = 260;
const YAW = 0.38;
const PITCH = 0.48;
const FOCAL = 1250;
const LABEL_ADVANCE = 10.2;

export function rangeLift(horizon: number, growth: number = RANGE_GROWTH): number {
  return 1.05 + growth * horizon;
}

export function projectPoint({ x, y, z }: Point3): Point2 {
  const horizontal = x * Math.cos(YAW) + z * Math.sin(YAW);
  const distance = -x * Math.sin(YAW) + z * Math.cos(YAW);
  const vertical = y * Math.cos(PITCH) + distance * Math.sin(PITCH);
  const depth = FOCAL + distance * Math.cos(PITCH) - y * Math.sin(PITCH);
  return { x: horizontal * FOCAL / depth, y: -vertical * FOCAL / depth, depth };
}

function polygon(points: Point3[]): string {
  return points.map((point) => {
    const projected = projectPoint(point);
    return `${projected.x.toFixed(2)},${projected.y.toFixed(2)}`;
  }).join(" ");
}

export function prismFaces(prism: Prism): { front: string; side: string; top: string; floor: string; shadow: string } {
  const { x, z, width, height, depth } = prism;
  const a = { x, y: 0, z };
  const b = { x: x + width, y: 0, z };
  const c = { x: x + width, y: 0, z: z + depth };
  const d = { x, y: 0, z: z + depth };
  const top = (point: Point3) => ({ ...point, y: height });
  const shadow = (point: Point3) => ({ x: point.x + height * 0.32, y: 0, z: point.z + height * 0.45 });
  return {
    front: polygon([top(a), top(b), b, a]),
    side: polygon([top(b), top(c), c, b]),
    top: polygon([top(a), top(d), top(c), top(b)]),
    floor: polygon([a, b, c, d]),
    shadow: polygon([a, b, shadow(c), shadow(d)]),
  };
}

function facePoints(faces: string[]): Array<[number, number]> {
  return faces.flatMap((face) => face.split(" ").map((pair) => {
    const [x = 0, y = 0] = pair.split(",").map(Number);
    return [x, y] as [number, number];
  }));
}

export function buildScape(layers: Layer[], growth: number = RANGE_GROWTH): Scape {
  const rows = Math.max(layers.length, 1);
  const historyLength = Math.max(0, ...layers.map((layer) => layer.history.length));
  const futureLength = Math.max(0, ...layers.map((layer) => layer.future.length));
  const steps = historyLength + futureLength;
  const width = Math.min(42, SPAN / Math.max(steps, 1) * 0.68);
  const spacing = (SPAN - width) / Math.max(steps - 1, 1);
  const peak = Math.max(1, ...layers.flatMap((layer) => [
    ...layer.history,
    ...layer.future.map((value, index) => value * rangeLift(index + 1, growth)),
  ]));
  const scale = PLOT_HEIGHT / peak;
  const prisms: Prism[] = [];
  for (let row = 0; row < layers.length; row++) {
    const layer = layers[row]!;
    for (let step = 0; step < steps; step++) {
      const historical = step < historyLength;
      const horizon = historical ? 0 : step - historyLength + 1;
      const value = Math.max(0, (historical ? layer.history[step] : layer.future[step - historyLength]) ?? 0);
      const x = -SPAN / 2 + step * spacing;
      const z = row * ROW_GAP;
      const base = { row, step, horizon, x, z, width, depth: 48, cameraDepth: projectPoint({ x: x + width / 2, y: 0, z: z + 24 }).depth };
      if (!historical) {
        const lift = rangeLift(horizon, growth);
        prisms.push({ ...base, key: `range-${row}-${step}`, tone: "range", height: value * scale * lift, shellFloor: 1 / lift });
      }
      prisms.push({ ...base, key: `${historical ? "history" : "future"}-${row}-${step}`, tone: historical ? "history" : "future", height: value * scale, shellFloor: 0 });
    }
  }
  prisms.sort((a, b) => b.cameraDepth - a.cameraDepth || (a.tone === "range" ? -1 : b.tone === "range" ? 1 : 0));

  const back = (rows - 1) * ROW_GAP + 100;
  const ground = polygon([
    { x: -SPAN / 2 - 30, y: 0, z: -32 }, { x: SPAN / 2 + 110, y: 0, z: -32 },
    { x: SPAN / 2 + 110, y: 0, z: back + 100 }, { x: -SPAN / 2 - 30, y: 0, z: back + 100 },
  ]);
  const envelope = facePoints([ground, polygon([
    { x: -SPAN / 2, y: PLOT_HEIGHT, z: 0 }, { x: SPAN / 2, y: PLOT_HEIGHT, z: 0 },
    { x: -SPAN / 2, y: PLOT_HEIGHT, z: back }, { x: SPAN / 2, y: PLOT_HEIGHT, z: back },
  ])]);
  const minX = Math.min(...envelope.map(([x]) => x));
  const maxX = Math.max(...envelope.map(([x]) => x));
  const minY = Math.min(...envelope.map(([, y]) => y));
  const maxY = Math.max(...envelope.map(([, y]) => y));
  const left = minX - 155;
  const top = minY - 35;
  const boxWidth = maxX - minX + 280;
  const boxHeight = maxY - minY + 110;
  const guide = (key: string, a: Point3, b: Point3): Guide => {
    const start = projectPoint(a);
    const end = projectPoint(b);
    return { key, x1: start.x, y1: start.y, x2: end.x, y2: end.y };
  };
  const guides = Array.from({ length: rows + 1 }, (_, row) => guide(`floor-${row}`,
    { x: -SPAN / 2, y: 0, z: row * ROW_GAP - 25 }, { x: SPAN / 2 + 50, y: 0, z: row * ROW_GAP - 25 }));
  const boundaryX = -SPAN / 2 + (historyLength - 0.5) * spacing;
  const boundary = guide("today", { x: boundaryX, y: 0, z: -25 }, { x: boundaryX, y: 0, z: back });
  const rowLabels: Label[] = layers.map((layer, row) => ({
    key: `row-${layer.id}`, x: minX - 15,
    y: projectPoint({ x: -SPAN / 2, y: 0, z: row * ROW_GAP }).y + 5,
    text: layer.label, anchor: "end",
  }));
  const labels: Label[] = [
    { key: "past", x: left + 10, y: Math.min(0, ...rowLabels.map((label) => label.y)) - 35, text: `${historyLength} weeks ago`, anchor: "start" },
    { key: "today", x: boundary.x1, y: maxY + 42, text: "today", anchor: "middle" },
    { key: "horizon", x: maxX + 115, y: maxY + 15, text: `+${futureLength} weeks`, anchor: "end" },
  ];
  const columns = Array.from({ length: steps }, (_, step) => ({
    step,
    bands: Array.from({ length: layers.length }, (_, row) => {
      const points = prisms.filter((prism) => prism.step === step && prism.row === row).flatMap((prism) => {
        const faces = prismFaces(prism);
        return facePoints([faces.front, faces.side, faces.top]);
      });
      const x = Math.min(...points.map(([px]) => px));
      return { key: `band-${row}`, x, width: Math.max(...points.map(([px]) => px)) - x,
        y1: Math.min(...points.map(([, py]) => py)) - 8, y2: Math.max(...points.map(([, py]) => py)) };
    }),
  }));
  return { viewBox: `${left} ${top} ${boxWidth} ${boxHeight}`, width: boxWidth, height: boxHeight,
    prisms, guides, labels, rowLabels, boundary, columns, ground, rows, steps, historyLength, futureLength };
}

export function labelWidth(text: string): number {
  return text.length * LABEL_ADVANCE;
}

export function scapeVertices(scape: Scape): Array<[number, number]> {
  return scape.prisms.flatMap((prism) => {
    const faces = prismFaces(prism);
    return facePoints([faces.front, faces.side, faces.top]);
  });
}

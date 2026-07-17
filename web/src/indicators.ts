import type { Bar } from './api';

export type Indicator =
  | { id: string; kind: 'sma' | 'ema'; period: number }
  | { id: string; kind: 'bb'; period: number; multiplier: number }
  | { id: string; kind: 'volume' }
  | { id: string; kind: 'rsi'; period: number }
  | { id: string; kind: 'macd'; fast: number; slow: number; signal: number };

export type Point = { time: number; value: number };
const closes = (bars: Bar[]) => bars.map((bar) => bar.close);

export function sma(bars: Bar[], period: number): Point[] {
  const values = closes(bars); let sum = 0;
  return values.flatMap((value, index) => { sum += value; if (index >= period) sum -= values[index - period]; return index >= period - 1 ? [{ time: bars[index].time, value: sum / period }] : []; });
}
export function ema(bars: Bar[], period: number): Point[] {
  const alpha = 2 / (period + 1); let previous: number | undefined;
  return closes(bars).map((value, index) => { previous = previous === undefined ? value : value * alpha + previous * (1 - alpha); return { time: bars[index].time, value: previous }; });
}
export function bollinger(bars: Bar[], period: number, multiplier: number): { middle: Point[]; upper: Point[]; lower: Point[] } {
  const values = closes(bars); const middle = sma(bars, period); const upper: Point[] = []; const lower: Point[] = [];
  for (let index = period - 1; index < values.length; index++) { const window = values.slice(index - period + 1, index + 1); const mean = window.reduce((a, b) => a + b, 0) / period; const sd = Math.sqrt(window.reduce((a, b) => a + (b - mean) ** 2, 0) / period); upper.push({ time: bars[index].time, value: mean + multiplier * sd }); lower.push({ time: bars[index].time, value: mean - multiplier * sd }); }
  return { middle, upper, lower };
}
export function rsi(bars: Bar[], period: number): Point[] {
  if (bars.length <= period) return []; const values = closes(bars); let gain = 0; let loss = 0;
  for (let i = 1; i <= period; i++) { const d = values[i] - values[i - 1]; gain += Math.max(0, d); loss += Math.max(0, -d); }
  gain /= period; loss /= period; const out: Point[] = [{ time: bars[period].time, value: 100 - 100 / (1 + gain / (loss || 1e-12)) }];
  for (let i = period + 1; i < values.length; i++) { const d = values[i] - values[i - 1]; gain = (gain * (period - 1) + Math.max(0, d)) / period; loss = (loss * (period - 1) + Math.max(0, -d)) / period; out.push({ time: bars[i].time, value: 100 - 100 / (1 + gain / (loss || 1e-12)) }); }
  return out;
}
export function macd(bars: Bar[], fast: number, slow: number, signal: number): { line: Point[]; signal: Point[]; histogram: Point[] } {
  const fastMap = new Map(ema(bars, fast).map((p) => [p.time, p.value])); const slowMap = new Map(ema(bars, slow).map((p) => [p.time, p.value]));
  const line = bars.flatMap((bar) => fastMap.has(bar.time) && slowMap.has(bar.time) ? [{ time: bar.time, value: fastMap.get(bar.time)! - slowMap.get(bar.time)! }] : []); const signalValues = ema(line.map((p) => ({ time: p.time, close: p.value })) as Bar[], signal); const sm = new Map(signalValues.map((p) => [p.time, p.value]));
  return { line, signal: signalValues, histogram: line.flatMap((p) => sm.has(p.time) ? [{ time: p.time, value: p.value - sm.get(p.time)! }] : []) };
}

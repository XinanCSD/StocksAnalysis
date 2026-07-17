import { describe, expect, it } from 'vitest';
import { bollinger, ema, macd, rsi, sma } from './indicators';

const bars = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26].map((close, i) => ({ time: i + 1, open: close - 1, high: close + 1, low: close - 2, close, volume: 100 + i }));

describe('technical indicators', () => {
  it('calculates SMA and EMA', () => {
    expect(sma(bars, 3).at(-1)).toEqual({ time: 17, value: 25 });
    expect(ema(bars, 3).at(-1)?.value).toBeGreaterThan(24);
  });
  it('calculates Bollinger bands', () => {
    const result = bollinger(bars, 5, 2);
    expect(result.middle).toHaveLength(13);
    expect(result.upper.at(-1)!.value).toBeGreaterThan(result.lower.at(-1)!.value);
  });
  it('calculates bounded RSI', () => {
    const values = rsi(bars, 14).map((point) => point.value);
    expect(values.every((value) => value >= 0 && value <= 100)).toBe(true);
  });
  it('calculates MACD line, signal and histogram', () => {
    const result = macd(bars, 3, 6, 2);
    expect(result.line.length).toBe(bars.length);
    expect(result.signal.length).toBe(bars.length);
    expect(result.histogram.length).toBe(bars.length);
  });
});

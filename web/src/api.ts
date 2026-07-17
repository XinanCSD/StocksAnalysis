export type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type SymbolInfo = {
  symbol: string; yahoo_symbol: string; enabled: boolean; daily_updated_at: string | null;
  intraday_updated_at: string | null; daily_rows: number; intraday_rows: number;
  last_error: string | null; task: { status: string; stage?: string }; data_version: string;
};
export type ChartResponse = { symbol: string; interval: string; source_interval: string; source_table: string; timezone: string; session: string; data_version: string; bars: Bar[] };

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.error?.message || body?.error?.message || `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  symbols: () => request<{ symbols: SymbolInfo[]; has_extended_hours: boolean }>('/api/symbols'),
  chart: (symbol: string, interval: string, session: string, start?: number) => {
    const params = new URLSearchParams({ symbol, interval, session, limit: '5000' });
    if (start) params.set('start', String(start));
    return request<ChartResponse>(`/api/chart?${params}`);
  },
  add: (symbol: string) => request<{ status: string }>('/api/symbols', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) }),
  refresh: (symbol: string) => request<{ status: string }>(`/api/symbols/${encodeURIComponent(symbol)}/refresh`, { method: 'POST' }),
};

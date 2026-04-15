const BASE = '/api';

async function fetchJson(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `API error: ${res.status}`);
  }
  return data;
}

export function healthCheck() {
  return fetchJson(`${BASE}/health`);
}

export function searchStocks(apikey, query) {
  return fetchJson(`${BASE}/search?apikey=${encodeURIComponent(apikey)}&query=${encodeURIComponent(query)}`);
}

export function screenStocks(apikey, { sector, capMin, capMax, limit } = {}) {
  let url = `${BASE}/screen?apikey=${encodeURIComponent(apikey)}`;
  if (sector) url += `&sector=${encodeURIComponent(sector)}`;
  if (capMin) url += `&capMin=${capMin}`;
  if (capMax) url += `&capMax=${capMax}`;
  if (limit) url += `&limit=${limit}`;
  return fetchJson(url);
}

export function analyzeStock(apikey, symbol) {
  return fetchJson(`${BASE}/analyze/${encodeURIComponent(symbol)}?apikey=${encodeURIComponent(apikey)}`);
}

export function backtestStock(apikey, symbol, { mos, sellPremium, years } = {}) {
  let url = `${BASE}/backtest/${encodeURIComponent(symbol)}?apikey=${encodeURIComponent(apikey)}`;
  if (mos) url += `&mos=${mos}`;
  if (sellPremium) url += `&sellPremium=${sellPremium}`;
  if (years) url += `&years=${years}`;
  return fetchJson(url);
}

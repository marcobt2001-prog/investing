const BASE = '/api';

async function fetchJson(url, options) {
  const res = await fetch(url, options);
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
  const params = new URLSearchParams({ query });
  if (apikey) params.set('apikey', apikey);
  return fetchJson(`${BASE}/search?${params.toString()}`);
}

// ----- Phase 2: DB-backed screener -----

function buildScreenParams(opts = {}) {
  const params = new URLSearchParams();
  if (opts.apikey) params.set('apikey', opts.apikey);
  if (opts.sector) params.set('sector', opts.sector);
  if (opts.industry) params.set('industry', opts.industry);
  if (opts.capMin) params.set('capMin', opts.capMin);
  if (opts.capMax) params.set('capMax', opts.capMax);
  if (opts.grahamGrade) params.set('grahamGrade', opts.grahamGrade);
  if (opts.fisherGrade) params.set('fisherGrade', opts.fisherGrade);
  if (opts.minGrahamScore != null && opts.minGrahamScore !== '') params.set('minGrahamScore', opts.minGrahamScore);
  if (opts.minFisherScore != null && opts.minFisherScore !== '') params.set('minFisherScore', opts.minFisherScore);
  if (opts.signal) params.set('signal', opts.signal);
  if (opts.minDiscount != null && opts.minDiscount !== '') params.set('minDiscount', opts.minDiscount);
  if (opts.ivTrend) params.set('ivTrend', opts.ivTrend);
  if (opts.sortBy) params.set('sortBy', opts.sortBy);
  if (opts.sortDir) params.set('sortDir', opts.sortDir);
  if (opts.limit) params.set('limit', opts.limit);
  return params;
}

export function screenStocks(opts = {}) {
  return fetchJson(`${BASE}/screen?${buildScreenParams(opts).toString()}`);
}

// Returns the URL the user can navigate to / download from.
export function screenExportUrl(opts = {}) {
  return `${BASE}/screen/export?${buildScreenParams(opts).toString()}`;
}

export function getSectors() {
  return fetchJson(`${BASE}/sectors`);
}

export function getDbStats() {
  return fetchJson(`${BASE}/db/stats`);
}

export function ingestSymbols(symbols, { skipExisting = true } = {}) {
  return fetchJson(`${BASE}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbols, skipExisting }),
  });
}

export function ingestUniverse(universe, { skipExisting = true } = {}) {
  return fetchJson(`${BASE}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ universe, skipExisting }),
  });
}

// ----- Phase 3: industries + two-phase ingestion -----

export function getIndustries({ sector, minCount } = {}) {
  const params = new URLSearchParams();
  if (sector) params.set('sector', sector);
  if (minCount != null) params.set('min_count', minCount);
  const qs = params.toString();
  return fetchJson(`${BASE}/industries${qs ? `?${qs}` : ''}`);
}

export function getIndustryCompanies(industry, { limit, sortBy } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set('limit', limit);
  if (sortBy) params.set('sort_by', sortBy);
  const qs = params.toString();
  return fetchJson(`${BASE}/industries/${encodeURIComponent(industry)}/companies${qs ? `?${qs}` : ''}`);
}

export function getIndustryStatus(industry) {
  return fetchJson(`${BASE}/industries/${encodeURIComponent(industry)}/status`);
}

export function getIndustryAccuracy(industry) {
  return fetchJson(`${BASE}/industries/${encodeURIComponent(industry)}/accuracy`);
}

export function discoverUniverse({ sample } = {}) {
  return fetchJson(`${BASE}/ingest/discover`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sample ? { sample } : {}),
  });
}

export function deepIngestIndustry(industry, { limit } = {}) {
  return fetchJson(`${BASE}/ingest/industry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ industry, ...(limit ? { limit } : {}) }),
  });
}

// ----- Existing analyze / backtest, now with optional apikey -----

export function analyzeStock(apikey, symbol, { refresh = false } = {}) {
  const params = new URLSearchParams();
  if (apikey) params.set('apikey', apikey);
  if (refresh) params.set('refresh', '1');
  const qs = params.toString();
  return fetchJson(`${BASE}/analyze/${encodeURIComponent(symbol)}${qs ? `?${qs}` : ''}`);
}

export function backtestStock(apikey, symbol, { mos, sellPremium, years } = {}) {
  const params = new URLSearchParams();
  if (apikey) params.set('apikey', apikey);
  if (mos) params.set('mos', mos);
  if (sellPremium) params.set('sellPremium', sellPremium);
  if (years) params.set('years', years);
  const qs = params.toString();
  return fetchJson(`${BASE}/backtest/${encodeURIComponent(symbol)}${qs ? `?${qs}` : ''}`);
}

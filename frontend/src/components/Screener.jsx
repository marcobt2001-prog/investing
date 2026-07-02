import { useState, useCallback, useEffect, useMemo } from 'react'
import {
  searchStocks,
  screenStocks,
  screenExportUrl,
  getSectors,
  getDbStats,
  ingestSymbols,
  ingestUniverse,
  getIndustries,
  discoverUniverse,
} from '../utils/api'
import { formatLargeCurrency } from '../utils/format'

const CAP_RANGES = [
  { label: 'All Caps', min: '', max: '' },
  { label: 'Mega (>$200B)', min: '200000000000', max: '' },
  { label: 'Large ($10B-$200B)', min: '10000000000', max: '200000000000' },
  { label: 'Mid ($2B-$10B)', min: '2000000000', max: '10000000000' },
  { label: 'Small ($300M-$2B)', min: '300000000', max: '2000000000' },
  { label: 'Micro (<$300M)', min: '', max: '300000000' },
]

const GRADES = ['', 'A', 'B', 'C', 'D']
const SIGNALS = ['', 'STRONG BUY', 'BUY', 'HOLD', 'OVERVALUED', 'STRONG SELL']

const SORT_OPTIONS = [
  { value: 'graham_pct', label: 'Graham Score' },
  { value: 'fisher_pct', label: 'Fisher Score' },
  { value: 'discount_to_intrinsic', label: 'Discount to Intrinsic' },
  { value: 'iv_cagr_5yr', label: 'IV Growth (5yr)' },
  { value: 'iv_cagr_10yr', label: 'IV Growth (10yr)' },
  { value: 'iv_stability', label: 'IV Stability' },
  { value: 'market_cap', label: 'Market Cap' },
  { value: 'price', label: 'Price' },
  { value: 'symbol', label: 'Symbol' },
]

const IV_TRENDS = ['', 'Growing', 'Stable', 'Declining']

function gradeColor(grade) {
  if (grade === 'A') return 'var(--green)'
  if (grade === 'B') return 'var(--blue)'
  if (grade === 'C') return 'var(--amber)'
  if (grade === 'D') return 'var(--red)'
  return 'var(--text-muted)'
}

function signalColor(signal) {
  if (!signal) return 'var(--text-muted)'
  if (signal === 'STRONG BUY') return 'var(--green)'
  if (signal === 'BUY') return 'var(--blue)'
  if (signal === 'HOLD') return 'var(--amber)'
  if (signal === 'OVERVALUED') return 'var(--red)'
  if (signal === 'STRONG SELL') return 'var(--red)'
  return 'var(--text-muted)'
}

function formatRelativeTime(iso) {
  if (!iso) return 'never'
  const ts = new Date(iso)
  const diffSec = Math.floor((Date.now() - ts.getTime()) / 1000)
  if (diffSec < 60) return 'just now'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

export default function Screener({ apiKey, onSelectStock }) {
  // ---- filter state ----
  const [sector, setSector] = useState('')
  const [industry, setIndustry] = useState('')
  const [capRange, setCapRange] = useState(0)
  const [grahamGrade, setGrahamGrade] = useState('')
  const [fisherGrade, setFisherGrade] = useState('')
  const [signal, setSignal] = useState('')
  const [minDiscount, setMinDiscount] = useState('')
  const [ivTrend, setIvTrend] = useState('')
  const [sortBy, setSortBy] = useState('graham_pct')
  const [sortDir, setSortDir] = useState('DESC')

  // ---- data state ----
  const [sectors, setSectors] = useState(['Technology', 'Healthcare', 'Consumer Defensive'])
  const [industries, setIndustries] = useState([])
  const [results, setResults] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // ---- search ----
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)

  // ---- ingest UI ----
  const [ingestSymbolsInput, setIngestSymbolsInput] = useState('')
  const [ingestStatus, setIngestStatus] = useState('')

  const filterArgs = useMemo(() => {
    const cap = CAP_RANGES[capRange] || CAP_RANGES[0]
    return {
      sector: sector || null,
      industry: industry || null,
      capMin: cap.min || null,
      capMax: cap.max || null,
      grahamGrade: grahamGrade || null,
      fisherGrade: fisherGrade || null,
      signal: signal || null,
      minDiscount: minDiscount === '' ? null : Number(minDiscount) / 100, // user enters %, API wants fraction
      ivTrend: ivTrend || null,
      sortBy,
      sortDir,
      limit: 100,
      apikey: apiKey || null,
    }
  }, [sector, industry, capRange, grahamGrade, fisherGrade, signal, minDiscount, ivTrend, sortBy, sortDir, apiKey])

  const runScreen = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await screenStocks(filterArgs)
      setResults(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e.message)
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [filterArgs])

  const refreshStats = useCallback(async () => {
    try {
      setStats(await getDbStats())
    } catch {
      // non-fatal
    }
  }, [])

  // Initial load: sectors + stats + first screen.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [s, st] = await Promise.all([getSectors(), getDbStats()])
        if (cancelled) return
        if (Array.isArray(s) && s.length) setSectors(s)
        setStats(st)
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    })()
    return () => { cancelled = true }
  }, [])

  // Load industries (filtered by sector when one is picked). Reset the
  // industry selection whenever the sector changes so we never keep a
  // sub-industry that doesn't belong to the new sector.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const inds = await getIndustries({ sector: sector || undefined, minCount: 1 })
        if (!cancelled) setIndustries(Array.isArray(inds) ? inds : [])
      } catch {
        if (!cancelled) setIndustries([])
      }
    })()
    return () => { cancelled = true }
  }, [sector])

  // If the current industry isn't valid for the loaded list, clear it.
  useEffect(() => {
    if (industry && industries.length && !industries.some((i) => i.industry === industry)) {
      setIndustry('')
    }
  }, [industries, industry])

  // Re-run the screen whenever filters change.
  useEffect(() => { runScreen() }, [runScreen])

  // ---- search ----
  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return
    setSearchLoading(true)
    setError('')
    try {
      const data = await searchStocks(apiKey, searchQuery)
      setSearchResults(data)
      setSearchOpen(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setSearchLoading(false)
    }
  }, [apiKey, searchQuery])

  const onSearchKeyDown = (e) => { if (e.key === 'Enter') handleSearch() }

  // ---- ingest actions ----
  const handleIngestStarter = async () => {
    setIngestStatus('Ingesting starter universe (this takes ~1 minute)...')
    try {
      const res = await ingestUniverse('starter', { skipExisting: true })
      setIngestStatus(`Done: ${res.ok}/${res.submitted} succeeded${res.failed ? `, ${res.failed} failed` : ''}.`)
      await refreshStats()
      await runScreen()
    } catch (e) {
      setIngestStatus(`Error: ${e.message}`)
    }
  }

  const handleIngestSymbols = async () => {
    const list = ingestSymbolsInput
      .split(/[,\s]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    if (!list.length) return
    setIngestStatus(`Ingesting ${list.join(', ')}...`)
    try {
      const res = await ingestSymbols(list, { skipExisting: false })
      setIngestStatus(`Done: ${res.ok}/${res.submitted} succeeded${res.failed ? `, ${res.failed} failed` : ''}.`)
      setIngestSymbolsInput('')
      await refreshStats()
      await runScreen()
    } catch (e) {
      setIngestStatus(`Error: ${e.message}`)
    }
  }

  const handleDiscoverUniverse = async () => {
    setIngestStatus('Discovering universe — light-ingesting company profiles. This can take 20-30 minutes for the full ~3000 tickers...')
    try {
      const res = await discoverUniverse()
      setIngestStatus(`Discovery done: ${res.ingested} company profiles ingested. Industries are now browsable.`)
      await refreshStats()
      // Reload industries for the (possibly new) sector.
      try {
        const inds = await getIndustries({ sector: sector || undefined, minCount: 1 })
        setIndustries(Array.isArray(inds) ? inds : [])
      } catch { /* non-fatal */ }
    } catch (e) {
      setIngestStatus(`Error: ${e.message}`)
    }
  }

  const exportHref = screenExportUrl(filterArgs)

  return (
    <div>
      {/* ---------- Data Status ---------- */}
      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex',
        flexWrap: 'wrap', gap: 16, alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 24, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', letterSpacing: 0.5 }}>COMPANIES</span>
            <div className="mono" style={{ fontSize: '1.1rem', color: 'var(--text-primary)' }}>
              {stats?.companies ?? '—'}
            </div>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', letterSpacing: 0.5 }}>FINANCIAL ROWS</span>
            <div className="mono" style={{ fontSize: '1.1rem' }}>{stats?.financials_rows ?? '—'}</div>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', letterSpacing: 0.5 }}>PRICES</span>
            <div className="mono" style={{ fontSize: '1.1rem' }}>{stats?.daily_prices_rows ?? '—'}</div>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', letterSpacing: 0.5 }}>LAST SCORED</span>
            <div className="mono" style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
              {formatRelativeTime(stats?.last_score_computed)}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn" onClick={refreshStats}>Refresh stats</button>
          <button className="btn btn-primary" onClick={handleIngestStarter}>
            Ingest starter (25 stocks)
          </button>
          <button className="btn" onClick={handleDiscoverUniverse}
            title="Light-ingest company profiles across the US-listed universe to populate industries">
            Discover Universe
          </button>
        </div>
      </div>

      {ingestStatus && (
        <div className="card" style={{ padding: '8px 16px', marginBottom: 16, color: 'var(--text-secondary)' }}>
          {ingestStatus}
        </div>
      )}

      {/* ---------- Search bar ---------- */}
      <div className="controls">
        <input
          type="text"
          placeholder="Search by company name or ticker (DB first, FMP if API key set)..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={onSearchKeyDown}
          style={{ flex: 1, minWidth: 240 }}
        />
        <button className="btn btn-primary" onClick={handleSearch} disabled={searchLoading || !searchQuery.trim()}>
          {searchLoading ? 'Searching...' : 'Search'}
        </button>
        {searchOpen && (
          <button className="btn" onClick={() => { setSearchOpen(false); setSearchResults([]) }}>
            Hide results
          </button>
        )}
      </div>

      {searchOpen && searchResults.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <h3 className="card-header">Search Results</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Name</th>
                <th>Exchange</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {searchResults.map((r) => (
                <tr key={r.symbol} className="clickable" onClick={() => onSelectStock(r.symbol)}>
                  <td className="mono" style={{ color: 'var(--green)', fontWeight: 600 }}>{r.symbol}</td>
                  <td>{r.name}</td>
                  <td style={{ color: 'var(--text-muted)' }}>{r.exchangeFullName || r.exchange}</td>
                  <td style={{ color: 'var(--blue)', cursor: 'pointer' }}>Analyze →</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {searchOpen && !searchLoading && searchResults.length === 0 && (
        <div className="card" style={{ marginBottom: 24, padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
          No results for "{searchQuery}". Add a ticker via the ingest controls below.
        </div>
      )}

      {/* ---------- Filters ---------- */}
      <h3 className="section-header">Filters</h3>
      <div className="controls" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          SECTOR
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="">All Sectors</option>
            {sectors.map((s) => (<option key={s} value={s}>{s}</option>))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          INDUSTRY
          <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
            <option value="">All Industries</option>
            {industries.map((i) => (
              <option key={i.industry} value={i.industry}>{i.industry} ({i.count})</option>
            ))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          MARKET CAP
          <select value={capRange} onChange={(e) => setCapRange(Number(e.target.value))}>
            {CAP_RANGES.map((r, i) => (<option key={r.label} value={i}>{r.label}</option>))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          GRAHAM GRADE
          <select value={grahamGrade} onChange={(e) => setGrahamGrade(e.target.value)}>
            {GRADES.map((g) => (<option key={g || 'all'} value={g}>{g || 'All'}</option>))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          FISHER GRADE
          <select value={fisherGrade} onChange={(e) => setFisherGrade(e.target.value)}>
            {GRADES.map((g) => (<option key={g || 'all'} value={g}>{g || 'All'}</option>))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          SIGNAL
          <select value={signal} onChange={(e) => setSignal(e.target.value)}>
            {SIGNALS.map((s) => (<option key={s || 'all'} value={s}>{s || 'All'}</option>))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          MIN DISCOUNT (%)
          <input
            type="number"
            placeholder="e.g. 20"
            value={minDiscount}
            onChange={(e) => setMinDiscount(e.target.value)}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          IV TREND
          <select value={ivTrend} onChange={(e) => setIvTrend(e.target.value)}>
            {IV_TRENDS.map((t) => (<option key={t || 'all'} value={t}>{t || 'All'}</option>))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          SORT BY
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            {SORT_OPTIONS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          DIRECTION
          <select value={sortDir} onChange={(e) => setSortDir(e.target.value)}>
            <option value="DESC">Descending</option>
            <option value="ASC">Ascending</option>
          </select>
        </label>
      </div>

      <div style={{ display: 'flex', gap: 12, marginTop: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <button className="btn" onClick={runScreen} disabled={loading}>
          {loading ? 'Running...' : 'Re-run'}
        </button>
        <a className="btn" href={exportHref} target="_blank" rel="noreferrer">Export CSV</a>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginLeft: 'auto' }}>
          {results.length} result{results.length === 1 ? '' : 's'}
        </span>
      </div>

      {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}

      {/* ---------- Results ---------- */}
      <div className="card" style={{ marginTop: 16 }}>
        {results.length === 0 && !loading ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
            {stats?.companies === 0
              ? 'No companies in the database yet. Click "Ingest starter" above to load 25 sample stocks.'
              : 'No companies match these filters.'}
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Name</th>
                <th>Sector</th>
                <th style={{ textAlign: 'right' }}>Mkt Cap</th>
                <th style={{ textAlign: 'right' }}>Price</th>
                <th style={{ textAlign: 'center' }}>Graham</th>
                <th style={{ textAlign: 'center' }}>Fisher</th>
                <th style={{ textAlign: 'right' }}>Intrinsic</th>
                <th style={{ textAlign: 'right' }}>Discount</th>
                <th style={{ textAlign: 'center' }}>IV Trend</th>
                <th>Signal</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.symbol} className="clickable" onClick={() => onSelectStock(r.symbol)}>
                  <td className="mono" style={{ color: 'var(--green)', fontWeight: 600 }}>{r.symbol}</td>
                  <td>{r.companyName}</td>
                  <td style={{ color: 'var(--text-muted)' }}>{r.sector || '—'}</td>
                  <td style={{ textAlign: 'right' }} className="mono">{formatLargeCurrency(r.marketCap)}</td>
                  <td style={{ textAlign: 'right' }} className="mono">{r.price != null ? `$${r.price.toFixed(2)}` : '—'}</td>
                  <td style={{ textAlign: 'center' }}>
                    <span style={{ color: gradeColor(r.grahamGrade), fontWeight: 700 }}>{r.grahamGrade || '—'}</span>
                    <span style={{ color: 'var(--text-muted)', marginLeft: 4, fontSize: '0.75rem' }}>
                      {r.grahamPct != null ? `${(r.grahamPct * 100).toFixed(0)}%` : ''}
                    </span>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <span style={{ color: gradeColor(r.fisherGrade), fontWeight: 700 }}>{r.fisherGrade || '—'}</span>
                    <span style={{ color: 'var(--text-muted)', marginLeft: 4, fontSize: '0.75rem' }}>
                      {r.fisherPct != null ? `${(r.fisherPct * 100).toFixed(0)}%` : ''}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }} className="mono">
                    {r.intrinsicValue != null ? `$${r.intrinsicValue.toFixed(2)}` : '—'}
                  </td>
                  <td style={{ textAlign: 'right' }} className="mono"
                      data-discount={r.discount}>
                    {r.discount != null ? (
                      <span style={{ color: r.discount > 0 ? 'var(--green)' : 'var(--red)' }}>
                        {(r.discount * 100).toFixed(1)}%
                      </span>
                    ) : '—'}
                  </td>
                  <td style={{ textAlign: 'center', fontSize: '0.8rem' }}>
                    {r.ivTrend ? (
                      <span style={{
                        color: r.ivTrend === 'growing' ? 'var(--green)'
                          : r.ivTrend === 'declining' ? 'var(--red)' : 'var(--amber)',
                        textTransform: 'capitalize',
                      }}>
                        {r.ivTrend}
                        {r.ivCagr5yr != null && (
                          <span style={{ color: 'var(--text-muted)', marginLeft: 4, fontSize: '0.72rem' }}>
                            {(r.ivCagr5yr * 100).toFixed(0)}%
                          </span>
                        )}
                      </span>
                    ) : '—'}
                  </td>
                  <td style={{ color: signalColor(r.signal), fontWeight: 600, fontSize: '0.85rem' }}>
                    {r.signal || '—'}
                  </td>
                  <td style={{ color: 'var(--blue)' }}>Analyze →</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ---------- Add tickers ---------- */}
      <h3 className="section-header" style={{ marginTop: 24 }}>Add Tickers</h3>
      <div className="card" style={{ padding: 16 }}>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: '0 0 12px 0' }}>
          Add specific tickers to the database. First ingest takes ~3s per ticker (EDGAR + yfinance). After
          that, screening and analysis are instant — no API calls.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input
            type="text"
            placeholder="AAPL, MSFT, NVDA, ..."
            value={ingestSymbolsInput}
            onChange={(e) => setIngestSymbolsInput(e.target.value)}
            style={{ flex: 1, minWidth: 240 }}
          />
          <button className="btn btn-primary" onClick={handleIngestSymbols} disabled={!ingestSymbolsInput.trim()}>
            Ingest
          </button>
        </div>
      </div>

      <p style={{ marginTop: 16, fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
        Phase 2: scores are pre-computed at ingestion time. Screening hits SQLite directly — no per-row API calls.
      </p>
    </div>
  )
}

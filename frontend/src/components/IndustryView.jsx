import { useState, useEffect, useCallback } from 'react'
import {
  getIndustries,
  getIndustryStatus,
  getIndustryAccuracy,
  deepIngestIndustry,
  screenStocks,
} from '../utils/api'
import { formatLargeCurrency } from '../utils/format'

const MODEL_LABELS = {
  graham: 'Graham', dcf: 'DCF', book_value: 'Book Value', epv: 'EPV', ncav: 'NCAV',
}

function StatusBar({ status }) {
  if (!status) return null
  const { total, with_financials, with_scores, profile_only } = status
  const pct = (n) => (total ? (n / total) * 100 : 0)
  return (
    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'baseline' }}>
      <div><span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>TOTAL</span>
        <div className="mono" style={{ fontSize: '1.1rem' }}>{total}</div></div>
      <div><span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>DEEP-INGESTED</span>
        <div className="mono" style={{ fontSize: '1.1rem', color: 'var(--green)' }}>{with_financials}</div></div>
      <div><span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>SCORED</span>
        <div className="mono" style={{ fontSize: '1.1rem', color: 'var(--blue)' }}>{with_scores}</div></div>
      <div><span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>PROFILE-ONLY</span>
        <div className="mono" style={{ fontSize: '1.1rem', color: 'var(--amber)' }}>{profile_only}</div></div>
      <div style={{ flex: 1, minWidth: 160 }}>
        <div style={{ background: 'rgba(255,255,255,0.05)', borderRadius: 4, height: 10, overflow: 'hidden', display: 'flex' }}>
          <div style={{ width: `${pct(with_financials)}%`, background: 'var(--green)' }} />
          <div style={{ width: `${pct(profile_only)}%`, background: 'var(--amber)' }} />
        </div>
      </div>
    </div>
  )
}

function AccuracyPanel({ accuracy }) {
  if (!accuracy?.rankings?.length) return null
  const ranked = [...accuracy.rankings].sort((a, b) => (a.rank || 99) - (b.rank || 99))
  const maxWeight = Math.max(0.01, ...ranked.map((r) => r.recommendedWeight || 0))
  return (
    <div className="card" style={{ padding: 16, marginTop: 16 }}>
      <h3 className="card-header">Valuation Model Accuracy</h3>
      <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 12px 0' }}>
        Most predictive model for this industry:{' '}
        <strong style={{ color: 'var(--green)' }}>{MODEL_LABELS[accuracy.bestModel3yr] || accuracy.bestModel3yr || '—'}</strong>.
        Rankings are by average 3-year prediction error (lower = better); weights are inverse-error normalized.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {ranked.map((r) => (
          <div key={r.model} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 24, textAlign: 'center', fontWeight: 700, color: r.rank === 1 ? 'var(--green)' : 'var(--text-muted)' }}>
              {r.rank}
            </div>
            <div style={{ width: 90, fontSize: '0.8rem' }}>{MODEL_LABELS[r.model] || r.model}</div>
            <div style={{ flex: 1, background: 'rgba(255,255,255,0.05)', borderRadius: 4, height: 18 }}>
              <div style={{
                width: `${((r.recommendedWeight || 0) / maxWeight) * 100}%`, height: '100%',
                background: r.rank === 1 ? 'var(--green)' : 'var(--blue)', borderRadius: 4,
              }} />
            </div>
            <div className="mono" style={{ width: 48, textAlign: 'right', fontSize: '0.8rem' }}>
              {r.recommendedWeight != null ? `${(r.recommendedWeight * 100).toFixed(0)}%` : '—'}
            </div>
            <div className="mono" style={{ width: 96, textAlign: 'right', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              err {r.avgError3yr != null ? r.avgError3yr.toFixed(2) : '—'} (n={r.sampleSize ?? 0})
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function IndustryView({ onSelectStock }) {
  const [industries, setIndustries] = useState([])
  const [selected, setSelected] = useState('')
  const [status, setStatus] = useState(null)
  const [accuracy, setAccuracy] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  // Load industries once.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const inds = await getIndustries({ minCount: 1 })
        if (!cancelled && Array.isArray(inds)) {
          setIndustries(inds)
          if (inds.length && !selected) setSelected(inds[0].industry)
        }
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadIndustry = useCallback(async (ind) => {
    if (!ind) return
    setLoading(true)
    setError('')
    setStatus(null)
    setAccuracy(null)
    setRows([])
    try {
      const [st, comps] = await Promise.all([
        getIndustryStatus(ind),
        screenStocks({ industry: ind, sortBy: 'graham_pct', sortDir: 'DESC', limit: 200 }),
      ])
      setStatus(st)
      setRows(Array.isArray(comps) ? comps : [])
      // Accuracy is best-effort — may 404 if no companies have enough history.
      try {
        setAccuracy(await getIndustryAccuracy(ind))
      } catch {
        setAccuracy(null)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadIndustry(selected) }, [selected, loadIndustry])

  const handleDeepIngest = async () => {
    if (!selected) return
    setIngesting(true)
    setMsg(`Deep-ingesting ${selected} — fetching EDGAR financials, prices, and scores. This can take a while for large industries...`)
    try {
      const res = await deepIngestIndustry(selected)
      setMsg(`Done: ${res.ingested} ingested, ${res.skipped} skipped, ${res.failed} failed.`
        + (res.accuracy?.best_model_3yr ? ` Best model: ${MODEL_LABELS[res.accuracy.best_model_3yr] || res.accuracy.best_model_3yr}.` : ''))
      await loadIndustry(selected)
    } catch (e) {
      setMsg(`Error: ${e.message}`)
    } finally {
      setIngesting(false)
    }
  }

  // Industry-level stats from the loaded rows.
  const scored = rows.filter((r) => r.grahamPct != null)
  const avgGraham = scored.length
    ? scored.reduce((s, r) => s + (r.grahamPct || 0), 0) / scored.length : null
  const best = scored.length
    ? scored.reduce((a, b) => ((b.grahamPct || 0) > (a.grahamPct || 0) ? b : a)) : null
  const worst = scored.length
    ? scored.reduce((a, b) => ((b.grahamPct || 0) < (a.grahamPct || 0) ? b : a)) : null

  return (
    <div>
      <div className="controls" style={{ alignItems: 'flex-end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)', flex: 1, minWidth: 280 }}>
          INDUSTRY
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {industries.length === 0 && <option value="">No industries — run Discover Universe first</option>}
            {industries.map((i) => (
              <option key={i.industry} value={i.industry}>
                {i.industry} — {i.count} companies ({i.sector})
              </option>
            ))}
          </select>
        </label>
        <button className="btn btn-primary" onClick={handleDeepIngest} disabled={ingesting || !selected}>
          {ingesting ? 'Ingesting...' : 'Deep Ingest All'}
        </button>
      </div>

      {msg && (
        <div className="card" style={{ padding: '8px 16px', marginBottom: 16, color: 'var(--text-secondary)' }}>{msg}</div>
      )}
      {error && <div className="error-msg" style={{ marginBottom: 16 }}>{error}</div>}

      {selected && (
        <>
          <div className="card" style={{ padding: 16, marginBottom: 16 }}>
            <h3 className="card-header">{selected}</h3>
            <StatusBar status={status} />
          </div>

          {/* Industry-level statistics */}
          {scored.length > 0 && (
            <div className="card" style={{ padding: 16, marginBottom: 16, display: 'flex', gap: 32, flexWrap: 'wrap' }}>
              <div><span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>AVG GRAHAM SCORE</span>
                <div className="mono" style={{ fontSize: '1.2rem' }}>{avgGraham != null ? `${(avgGraham * 100).toFixed(0)}%` : '—'}</div></div>
              {best && <div><span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>BEST</span>
                <div className="mono" style={{ color: 'var(--green)' }}>{best.symbol} ({(best.grahamPct * 100).toFixed(0)}%)</div></div>}
              {worst && <div><span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>WORST</span>
                <div className="mono" style={{ color: 'var(--red)' }}>{worst.symbol} ({(worst.grahamPct * 100).toFixed(0)}%)</div></div>}
            </div>
          )}

          <AccuracyPanel accuracy={accuracy} />

          {/* Company table */}
          <div className="card" style={{ marginTop: 16 }}>
            {loading ? (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>Loading...</div>
            ) : rows.length === 0 ? (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                No companies loaded. Click "Deep Ingest All" to fetch financials and scores for this industry.
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th><th>Name</th>
                    <th style={{ textAlign: 'right' }}>Mkt Cap</th>
                    <th style={{ textAlign: 'center' }}>Graham</th>
                    <th style={{ textAlign: 'center' }}>Fisher</th>
                    <th style={{ textAlign: 'right' }}>Discount</th>
                    <th style={{ textAlign: 'center' }}>IV Trend</th>
                    <th>Signal</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.symbol} className="clickable" onClick={() => onSelectStock(r.symbol)}>
                      <td className="mono" style={{ color: 'var(--green)', fontWeight: 600 }}>{r.symbol}</td>
                      <td>{r.companyName}</td>
                      <td style={{ textAlign: 'right' }} className="mono">{formatLargeCurrency(r.marketCap)}</td>
                      <td style={{ textAlign: 'center' }}>{r.grahamGrade || '—'}</td>
                      <td style={{ textAlign: 'center' }}>{r.fisherGrade || '—'}</td>
                      <td style={{ textAlign: 'right' }} className="mono">
                        {r.discount != null ? (
                          <span style={{ color: r.discount > 0 ? 'var(--green)' : 'var(--red)' }}>
                            {(r.discount * 100).toFixed(1)}%
                          </span>) : '—'}
                      </td>
                      <td style={{ textAlign: 'center', fontSize: '0.8rem',
                        color: r.ivTrend === 'growing' ? 'var(--green)' : r.ivTrend === 'declining' ? 'var(--red)' : 'var(--amber)',
                        textTransform: 'capitalize' }}>
                        {r.ivTrend || '—'}
                      </td>
                      <td style={{ fontSize: '0.85rem', fontWeight: 600 }}>{r.signal || '—'}</td>
                      <td style={{ color: 'var(--blue)' }}>Analyze →</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  )
}

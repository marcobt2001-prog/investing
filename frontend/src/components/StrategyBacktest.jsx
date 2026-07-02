import { useState, useCallback, useMemo } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts'
import { runStrategyBacktest, runStrategySweep } from '../utils/api'
import { formatCurrency } from '../utils/format'

const MOS_OPTIONS = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
const SELL_OPTIONS = [0.10, 0.15, 0.20, 0.30]
const YEARS = Array.from({ length: 11 }, (_, i) => 2015 + i)
const COMPLETENESS = [
  { label: '60%+', value: 0.6 }, { label: '70%+', value: 0.7 },
  { label: '80%+', value: 0.8 }, { label: '90%+', value: 0.9 },
]

const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

function SummaryCard({ label, value, positive }) {
  const color = positive == null ? 'var(--text-primary)' : positive ? 'var(--green)' : 'var(--red)'
  return (
    <div className="summary-card">
      <div className="summary-label">{label}</div>
      <div className="summary-value" style={{ color }}>{value}</div>
    </div>
  )
}

// Heatmap cell background: green scale for higher annualized return.
function heatColor(value, min, max) {
  if (value == null || max === min) return 'rgba(255,255,255,0.05)'
  const t = (value - min) / (max - min)
  // interpolate red(low) -> amber -> green(high)
  const r = t < 0.5 ? 220 : Math.round(220 - (t - 0.5) * 2 * 180)
  const g = t < 0.5 ? Math.round(t * 2 * 180) + 40 : 200
  return `rgba(${r}, ${g}, 60, ${0.25 + t * 0.5})`
}

export default function StrategyBacktest() {
  const [mos, setMos] = useState(0.30)
  const [sell, setSell] = useState(0.20)
  const [startYear, setStartYear] = useState(2015)
  const [endYear, setEndYear] = useState(2025)
  const [maxPositions, setMaxPositions] = useState(20)
  const [minCompleteness, setMinCompleteness] = useState(0.7)

  const [data, setData] = useState(null)
  const [sweep, setSweep] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sweeping, setSweeping] = useState(false)
  const [error, setError] = useState('')

  const params = useMemo(() => ({
    marginOfSafety: mos, sellPremium: sell,
    startYear: Number(startYear), endYear: Number(endYear),
    maxPositions: Number(maxPositions), minCompleteness: Number(minCompleteness),
  }), [mos, sell, startYear, endYear, maxPositions, minCompleteness])

  const doRun = useCallback(async () => {
    setLoading(true); setError(''); setData(null)
    try {
      setData(await runStrategyBacktest(params))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [params])

  const doSweep = useCallback(async () => {
    setSweeping(true); setError(''); setSweep(null)
    try {
      const res = await runStrategySweep({
        mosValues: MOS_OPTIONS, sellValues: SELL_OPTIONS,
        startYear: Number(startYear), endYear: Number(endYear),
        maxPositions: Number(maxPositions), minCompleteness: Number(minCompleteness),
      })
      setSweep(res.results || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setSweeping(false)
    }
  }, [startYear, endYear, maxPositions, minCompleteness])

  const summary = data?.summary

  // Merge portfolio + benchmark series into one dataset for the chart.
  const chartData = useMemo(() => {
    if (!data?.yearlyData) return []
    const bench = {}
    ;(data.benchmarkSeries || []).forEach((b) => { bench[b.year] = b.value })
    return data.yearlyData.map((y) => ({
      year: y.year,
      portfolio: y.portfolioValue,
      benchmark: bench[y.year] ?? null,
    }))
  }, [data])

  const sweepStats = useMemo(() => {
    if (!sweep?.length) return null
    const rets = sweep.map((s) => s.annualizedReturn).filter((v) => v != null)
    const best = sweep.reduce((a, b) => (b.annualizedReturn > a.annualizedReturn ? b : a))
    return { min: Math.min(...rets), max: Math.max(...rets), best }
  }, [sweep])

  return (
    <div>
      {/* Controls */}
      <div className="controls" style={{ flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          MARGIN OF SAFETY
          <select value={mos} onChange={(e) => setMos(Number(e.target.value))}>
            {MOS_OPTIONS.map((v) => <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          SELL PREMIUM
          <select value={sell} onChange={(e) => setSell(Number(e.target.value))}>
            {SELL_OPTIONS.map((v) => <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          START YEAR
          <select value={startYear} onChange={(e) => setStartYear(e.target.value)}>
            {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          END YEAR
          <select value={endYear} onChange={(e) => setEndYear(e.target.value)}>
            {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          MAX POSITIONS
          <input type="number" value={maxPositions} min={1} max={100}
            onChange={(e) => setMaxPositions(e.target.value)} style={{ width: 80 }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          MIN COMPLETENESS
          <select value={minCompleteness} onChange={(e) => setMinCompleteness(Number(e.target.value))}>
            {COMPLETENESS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <button className="btn btn-primary" onClick={doRun} disabled={loading || sweeping}>
          {loading ? 'Running...' : 'Run Strategy Backtest'}
        </button>
        <button className="btn" onClick={doSweep} disabled={loading || sweeping}
          title="Runs all margin-of-safety × sell-premium combinations (slower)">
          {sweeping ? 'Sweeping...' : 'Run Parameter Sweep'}
        </button>
      </div>

      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: '4px 0 16px 0' }}>
        Tests the strategy across every scored company: buy quality names (Graham/Fisher B+ with growing intrinsic
        value) at a discount, sell when they exceed intrinsic value. A full run re-scores thousands of companies for
        each year — expect 30-60 seconds.
      </p>

      {error && <div className="error-msg">{error}</div>}

      {(loading || sweeping) && (
        <div className="loading">
          <div className="loading-bars"><span /><span /><span /><span /><span /></div>
          <p>{sweeping ? 'Running parameter sweep across all combinations...' : 'Backtesting strategy across all companies...'}</p>
        </div>
      )}

      {summary && !loading && (
        <div className="fade-in">
          {/* Summary cards */}
          <div className="summary-cards">
            <SummaryCard label="Starting Capital" value={formatCurrency(summary.startingCapital)} />
            <SummaryCard label="Ending Value" value={formatCurrency(summary.endingValue)}
              positive={summary.endingValue >= summary.startingCapital} />
            <SummaryCard label="Total Return" value={pct(summary.totalReturn)} positive={summary.totalReturn >= 0} />
            <SummaryCard label="Annualized" value={pct(summary.annualizedReturn)} positive={summary.annualizedReturn >= 0} />
            <SummaryCard label="S&P 500 (annual)" value={pct(summary.benchmarkAnnualized)} />
            <SummaryCard label="Alpha" value={pct(summary.alpha)} positive={summary.alpha != null ? summary.alpha >= 0 : null} />
            <SummaryCard label="Max Drawdown" value={pct(summary.maxDrawdown)} positive={false} />
            <SummaryCard label="Win Rate" value={summary.winRate != null ? `${(summary.winRate * 100).toFixed(0)}%` : '—'} />
            <SummaryCard label="Avg Hold" value={summary.avgHoldingPeriod != null ? `${summary.avgHoldingPeriod} yr` : '—'} />
            <SummaryCard label="Sharpe" value={summary.sharpeRatio != null ? summary.sharpeRatio.toFixed(2) : '—'} />
          </div>

          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: '8px 0 16px 0' }}>
            {summary.companiesEvaluated} companies evaluated · {summary.companiesQualified} qualified · {summary.companiesBought} bought · {summary.totalTrades} closed trades
          </div>

          {/* Portfolio vs benchmark chart */}
          <h3 className="section-header">Portfolio vs S&P 500</h3>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ width: '100%', height: 340 }}>
              <ResponsiveContainer>
                <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="year" stroke="var(--text-muted)" fontSize={12} />
                  <YAxis stroke="var(--text-muted)" fontSize={12} width={70}
                    tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip
                    contentStyle={{ background: '#1a1f2e', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }}
                    formatter={(v) => (v != null ? formatCurrency(v) : '—')} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="portfolio" name="Strategy" stroke="#3b82f6" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="benchmark" name="S&P 500" stroke="#e2e8f0" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Year-by-year table */}
          <h3 className="section-header">Year-by-Year</h3>
          <div className="card" style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Year</th><th style={{ textAlign: 'right' }}>Portfolio</th>
                  <th style={{ textAlign: 'right' }}>Cash</th>
                  <th style={{ textAlign: 'center' }}># Pos</th>
                  <th style={{ textAlign: 'center' }}>Qualified</th>
                  <th style={{ textAlign: 'center' }}>Buys</th>
                  <th style={{ textAlign: 'center' }}>Sells</th>
                  <th style={{ textAlign: 'right' }}>YTD</th>
                </tr>
              </thead>
              <tbody>
                {data.yearlyData.map((y) => (
                  <tr key={y.year}>
                    <td className="mono">{y.year}</td>
                    <td className="mono" style={{ textAlign: 'right', fontWeight: 600 }}>{formatCurrency(y.portfolioValue)}</td>
                    <td className="mono" style={{ textAlign: 'right' }}>{formatCurrency(y.cash)}</td>
                    <td style={{ textAlign: 'center' }}>{y.positionCount}</td>
                    <td style={{ textAlign: 'center', color: 'var(--text-muted)' }}>{y.qualifiedCount}</td>
                    <td style={{ textAlign: 'center', color: 'var(--green)' }}>{y.buys.length || ''}</td>
                    <td style={{ textAlign: 'center', color: 'var(--amber)' }}>{y.sells.length || ''}</td>
                    <td className="mono" style={{ textAlign: 'right', color: y.returnYTD >= 0 ? 'var(--green)' : 'var(--red)' }}>
                      {pct(y.returnYTD)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Trade log */}
          {data.allTrades?.length > 0 && (
            <>
              <h3 className="section-header">Trade Log ({data.allTrades.length})</h3>
              <div className="card" style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Symbol</th><th>Buy Yr</th>
                      <th style={{ textAlign: 'right' }}>Buy Px</th>
                      <th style={{ textAlign: 'right' }}>Buy IV</th>
                      <th style={{ textAlign: 'right' }}>Discount</th>
                      <th>Sell Yr</th>
                      <th style={{ textAlign: 'right' }}>Sell Px</th>
                      <th style={{ textAlign: 'right' }}>Return</th>
                      <th style={{ textAlign: 'center' }}>Hold</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.allTrades.map((t, i) => (
                      <tr key={i}>
                        <td className="mono" style={{ color: 'var(--green)', fontWeight: 600 }}>{t.symbol}</td>
                        <td className="mono">{t.buyYear}</td>
                        <td className="mono" style={{ textAlign: 'right' }}>{formatCurrency(t.buyPrice)}</td>
                        <td className="mono" style={{ textAlign: 'right' }}>{formatCurrency(t.buyIV)}</td>
                        <td className="mono" style={{ textAlign: 'right', color: 'var(--green)' }}>{pct(t.buyDiscount)}</td>
                        <td className="mono">{t.sellYear}</td>
                        <td className="mono" style={{ textAlign: 'right' }}>{formatCurrency(t.sellPrice)}</td>
                        <td className="mono" style={{ textAlign: 'right', fontWeight: 600, color: t.returnPct >= 0 ? 'var(--green)' : 'var(--red)' }}>
                          {pct(t.returnPct)}
                        </td>
                        <td style={{ textAlign: 'center' }}>{t.holdingYears}y</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {/* Parameter sweep results */}
      {sweep && sweepStats && (
        <>
          <h3 className="section-header">Parameter Sweep — Annualized Return</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: '0 0 12px 0' }}>
            Best: {(sweepStats.best.marginOfSafety * 100).toFixed(0)}% MoS × {(sweepStats.best.sellPremium * 100).toFixed(0)}% sell
            → <strong style={{ color: 'var(--green)' }}>{pct(sweepStats.best.annualizedReturn)}</strong> annualized
            (Sharpe {sweepStats.best.sharpeRatio != null ? sweepStats.best.sharpeRatio.toFixed(2) : '—'})
          </p>
          <div className="card" style={{ overflowX: 'auto', padding: 16 }}>
            <table className="data-table" style={{ textAlign: 'center' }}>
              <thead>
                <tr>
                  <th>MoS \ Sell →</th>
                  {SELL_OPTIONS.map((s) => <th key={s} style={{ textAlign: 'center' }}>{(s * 100).toFixed(0)}%</th>)}
                </tr>
              </thead>
              <tbody>
                {MOS_OPTIONS.map((m) => (
                  <tr key={m}>
                    <td className="mono" style={{ fontWeight: 600 }}>{(m * 100).toFixed(0)}%</td>
                    {SELL_OPTIONS.map((s) => {
                      const cell = sweep.find((r) => r.marginOfSafety === m && r.sellPremium === s)
                      const v = cell?.annualizedReturn
                      const isBest = cell === sweepStats.best
                      return (
                        <td key={s} className="mono"
                          style={{
                            background: heatColor(v, sweepStats.min, sweepStats.max),
                            fontWeight: isBest ? 700 : 400,
                            outline: isBest ? '2px solid var(--green)' : 'none',
                          }}
                          title={cell ? `Sharpe ${cell.sharpeRatio ?? '—'}, ${cell.totalTrades} trades, win ${cell.winRate != null ? (cell.winRate * 100).toFixed(0) + '%' : '—'}` : ''}>
                          {pct(v)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!data && !sweep && !loading && !sweeping && !error && (
        <div className="empty-state">
          <h3>Cross-Company Strategy Backtest</h3>
          <p>Test the value strategy across your entire database. Set parameters above and run.</p>
        </div>
      )}
    </div>
  )
}

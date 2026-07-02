import { useState, useEffect, useCallback } from 'react'
import { backtestStock } from '../utils/api'
import { formatCurrency, formatPercent } from '../utils/format'
import StrategyBacktest from './StrategyBacktest'

export default function Backtest({ apiKey, initialSymbol }) {
  const [mode, setMode] = useState('single') // 'single' | 'strategy'
  const [symbol, setSymbol] = useState(initialSymbol || '')
  const [mos, setMos] = useState('0.35')
  const [sellPremium, setSellPremium] = useState('0.20')
  const [years, setYears] = useState('5')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const doBacktest = useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    setError('')
    setData(null)
    try {
      const result = await backtestStock(apiKey, symbol, {
        mos,
        sellPremium,
        years,
      })
      setData(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [apiKey, symbol, mos, sellPremium, years])

  useEffect(() => {
    if (initialSymbol) {
      setSymbol(initialSymbol)
    }
  }, [initialSymbol])

  const handleSubmit = (e) => {
    e.preventDefault()
    doBacktest()
  }

  const summary = data?.summary

  return (
    <div>
      {/* Sub-tab toggle */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button className={`btn ${mode === 'single' ? 'btn-primary' : ''}`} onClick={() => setMode('single')}>
          Single Company
        </button>
        <button className={`btn ${mode === 'strategy' ? 'btn-primary' : ''}`} onClick={() => setMode('strategy')}>
          Strategy (All Companies)
        </button>
      </div>

      {mode === 'strategy' && <StrategyBacktest />}

      {mode === 'single' && (
      <>
      {/* Controls */}
      <form className="controls" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Ticker (e.g. AAPL)"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          style={{ width: 140, fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}
        />
        <select value={mos} onChange={(e) => setMos(e.target.value)}>
          <option value="0.20">20% MoS</option>
          <option value="0.25">25% MoS</option>
          <option value="0.30">30% MoS</option>
          <option value="0.35">35% MoS</option>
          <option value="0.40">40% MoS</option>
          <option value="0.50">50% MoS</option>
        </select>
        <select value={sellPremium} onChange={(e) => setSellPremium(e.target.value)}>
          <option value="0.10">10% Sell Premium</option>
          <option value="0.15">15% Sell Premium</option>
          <option value="0.20">20% Sell Premium</option>
          <option value="0.25">25% Sell Premium</option>
          <option value="0.30">30% Sell Premium</option>
        </select>
        <select value={years} onChange={(e) => setYears(e.target.value)}>
          <option value="3">3 Years</option>
          <option value="5">5 Years</option>
          <option value="7">7 Years</option>
          <option value="10">10 Years</option>
        </select>
        <button className="btn btn-primary" type="submit" disabled={loading || !symbol.trim()}>
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </form>

      {error && <div className="error-msg">{error}</div>}

      {loading && (
        <div className="loading">
          <div className="loading-bars">
            <span /><span /><span /><span /><span />
          </div>
          <p>Running backtest simulation...</p>
        </div>
      )}

      {!data && !loading && !error && (
        <div className="empty-state">
          <h3>Configure Your Backtest</h3>
          <p>
            Enter a ticker, set your margin of safety and sell premium thresholds,
            then click Run Backtest to simulate a Graham-style value investing strategy.
          </p>
        </div>
      )}

      {data && !data.error && summary && (
        <div className="fade-in">
          {/* Summary Cards */}
          <div className="summary-cards">
            <div className="summary-card">
              <div className="summary-label">Starting Capital</div>
              <div className="summary-value">{formatCurrency(summary.startingCapital)}</div>
            </div>
            <div className="summary-card">
              <div className="summary-label">Ending Value</div>
              <div className={`summary-value ${summary.endingValue >= summary.startingCapital ? 'positive' : 'negative'}`}>
                {formatCurrency(summary.endingValue)}
              </div>
            </div>
            <div className="summary-card">
              <div className="summary-label">Total Return</div>
              <div className={`summary-value ${summary.totalReturn >= 0 ? 'positive' : 'negative'}`}>
                {formatPercent(summary.totalReturn)}
              </div>
            </div>
            <div className="summary-card">
              <div className="summary-label">Annualized Return</div>
              <div className={`summary-value ${summary.annualizedReturn >= 0 ? 'positive' : 'negative'}`}>
                {formatPercent(summary.annualizedReturn)}
              </div>
            </div>
          </div>

          {/* Year-by-Year Table */}
          <h3 className="section-header">Year-by-Year Performance</h3>
          <div className="card" style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Avg Price</th>
                  <th>Intrinsic Value</th>
                  <th>Discount</th>
                  <th>Action</th>
                  <th>Shares Held</th>
                  <th>Portfolio Value</th>
                </tr>
              </thead>
              <tbody>
                {data.yearlyData.map((row) => (
                  <tr key={row.year}>
                    <td className="mono">{row.year}</td>
                    <td className="mono">{formatCurrency(row.avgPrice)}</td>
                    <td className="mono">{row.intrinsicValue ? formatCurrency(row.intrinsicValue) : 'N/A'}</td>
                    <td className="mono" style={{
                      color: row.discount > 0 ? 'var(--green)' : row.discount < 0 ? 'var(--red)' : 'var(--text-muted)'
                    }}>
                      {row.discount != null ? formatPercent(row.discount) : 'N/A'}
                    </td>
                    <td>
                      <span className={`action-badge ${row.action}`}>{row.action}</span>
                    </td>
                    <td className="mono">{row.sharesHeld.toLocaleString()}</td>
                    <td className="mono" style={{ fontWeight: 600 }}>{formatCurrency(row.portfolioValue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Trade Log */}
          {data.tradeLog && data.tradeLog.length > 0 && (
            <>
              <h3 className="section-header">Trade Log</h3>
              <div className="card">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th>Action</th>
                      <th>Shares</th>
                      <th>Price</th>
                      <th>Total</th>
                      <th>Discount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.tradeLog.map((trade, i) => (
                      <tr key={i}>
                        <td className="mono">{trade.year}</td>
                        <td>
                          <span className={`action-badge ${trade.action}`}>{trade.action}</span>
                        </td>
                        <td className="mono">{trade.shares.toLocaleString()}</td>
                        <td className="mono">{formatCurrency(trade.price)}</td>
                        <td className="mono">{formatCurrency(trade.total)}</td>
                        <td className="mono" style={{
                          color: trade.discount > 0 ? 'var(--green)' : 'var(--red)'
                        }}>
                          {formatPercent(trade.discount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {data.tradeLog && data.tradeLog.length === 0 && (
            <div className="card" style={{ marginTop: 24, textAlign: 'center', padding: 32, color: 'var(--text-muted)' }}>
              No trades were triggered during the backtest period. The stock never reached the required margin of safety for a buy signal.
            </div>
          )}
        </div>
      )}

      {data?.error && (
        <div className="error-msg">{data.error}</div>
      )}
      </>
      )}
    </div>
  )
}

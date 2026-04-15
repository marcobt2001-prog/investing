import { useState, useEffect, useCallback } from 'react'
import { analyzeStock } from '../utils/api'
import { formatCurrency, formatLargeCurrency, formatPercent } from '../utils/format'

function ScoreCard({ title, grade, score, maxScore, pctScore, extra }) {
  return (
    <div className="score-card">
      <div className="score-label">{title}</div>
      <div className={`grade ${grade}`}>{grade}</div>
      <div className="score-detail">
        {score}/{maxScore} ({(pctScore * 100).toFixed(0)}%)
      </div>
      {extra && <div className="score-detail" style={{ fontSize: '0.75rem' }}>{extra}</div>}
      <div className="progress-bar">
        <div className={`fill ${grade}`} style={{ width: `${pctScore * 100}%` }} />
      </div>
    </div>
  )
}

function ValuationCard({ compositeValue, currentPrice, discount, signal }) {
  return (
    <div className="score-card">
      <div className="score-label">Composite Intrinsic Value</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '2rem', fontWeight: 700, color: 'var(--blue)' }}>
        {compositeValue ? formatCurrency(compositeValue) : 'N/A'}
      </div>
      {discount != null && (
        <div className="score-detail" style={{ color: discount > 0 ? 'var(--green)' : 'var(--red)' }}>
          {formatPercent(discount)} vs market
        </div>
      )}
      {signal && (
        <div style={{ marginTop: 12 }}>
          <span className={`signal-badge ${signal.replace(/ /g, '_')}`}>{signal}</span>
        </div>
      )}
    </div>
  )
}

function CriterionRow({ label, value, threshold, score, manual, question }) {
  if (manual) {
    return (
      <div className="criterion manual-review">
        <div className="dot manual" />
        <div className="criterion-info">
          <div className="criterion-label">{label}</div>
          <div className="manual-badge">Manual Review Required</div>
          <div className="criterion-threshold">{question}</div>
        </div>
      </div>
    )
  }

  const dotClass = score >= 1 ? 'pass' : score > 0 ? 'partial' : 'fail'

  return (
    <div className="criterion">
      <div className={`dot ${dotClass}`} />
      <div className="criterion-info">
        <div className="criterion-label">{label}</div>
        <div className="criterion-value">{typeof value === 'number' ? formatCurrency(value) : String(value ?? 'N/A')}</div>
        <div className="criterion-threshold">{threshold}</div>
      </div>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontWeight: 700,
        fontSize: '0.9rem',
        color: score >= 1 ? 'var(--green)' : score > 0 ? 'var(--amber)' : 'var(--red)',
      }}>
        {score.toFixed(1)}
      </div>
    </div>
  )
}

export default function Analysis({ apiKey, initialSymbol, onBacktest }) {
  const [symbol, setSymbol] = useState(initialSymbol || '')
  const [inputSymbol, setInputSymbol] = useState(initialSymbol || '')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const doAnalyze = useCallback(async (sym) => {
    if (!sym) return
    setLoading(true)
    setError('')
    setData(null)
    try {
      const result = await analyzeStock(apiKey, sym)
      setData(result)
      setSymbol(sym.toUpperCase())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [apiKey])

  useEffect(() => {
    if (initialSymbol && initialSymbol !== symbol) {
      setInputSymbol(initialSymbol)
      doAnalyze(initialSymbol)
    }
  }, [initialSymbol])

  const handleSubmit = (e) => {
    e.preventDefault()
    doAnalyze(inputSymbol)
  }

  const profile = data?.profile?.[0] || {}
  const graham = data?.graham
  const fisher = data?.fisher
  const valuation = data?.valuation

  return (
    <div>
      {/* Input */}
      <form className="controls" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Enter ticker symbol (e.g. AAPL)"
          value={inputSymbol}
          onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
          style={{ width: 220, fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}
        />
        <button className="btn btn-primary" type="submit" disabled={loading || !inputSymbol.trim()}>
          {loading ? 'Analyzing...' : 'Analyze'}
        </button>
        {data && (
          <button
            type="button"
            className="btn"
            style={{ background: 'var(--blue-dim)', color: 'var(--blue)', border: '1px solid var(--blue)' }}
            onClick={() => onBacktest(symbol)}
          >
            Backtest {symbol}
          </button>
        )}
      </form>

      {error && <div className="error-msg">{error}</div>}

      {loading && (
        <div className="loading">
          <div className="loading-bars">
            <span /><span /><span /><span /><span />
          </div>
          <p>Fetching financial data and running analysis...</p>
          <p style={{ fontSize: '0.8rem', marginTop: 4 }}>This may take a few seconds (6 API calls)</p>
        </div>
      )}

      {!data && !loading && !error && (
        <div className="empty-state">
          <h3>Enter a Ticker Symbol</h3>
          <p>Type a stock symbol above and click Analyze to run Graham, Fisher, and valuation analysis.</p>
        </div>
      )}

      {data && (
        <div className="fade-in">
          {/* Company Header */}
          <div className="company-header">
            <div className="company-info">
              <h2>{profile.symbol} - {profile.companyName}</h2>
              <div className="company-meta">
                {profile.sector} / {profile.industry} &middot; {profile.exchange}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
              {valuation?.signal && (
                <span className={`signal-badge ${valuation.signal.replace(/ /g, '_')}`}>
                  {valuation.signal}
                </span>
              )}
              <div className="company-price">
                <div className="price">{formatCurrency(profile.price)}</div>
                <div className="market-cap">Mkt Cap: {formatLargeCurrency(profile.marketCap)}</div>
              </div>
            </div>
          </div>

          {/* Score Cards */}
          <div className="score-cards">
            {graham && (
              <ScoreCard
                title="Graham Score"
                grade={graham.grade}
                score={graham.totalScore}
                maxScore={graham.maxScore}
                pctScore={graham.pctScore}
              />
            )}
            {fisher && (
              <ScoreCard
                title="Fisher Score (Auto)"
                grade={fisher.grade}
                score={fisher.totalScore}
                maxScore={fisher.maxScore}
                pctScore={fisher.pctScore}
                extra={`${fisher.manualReviewCount} items need manual review`}
              />
            )}
            {valuation && (
              <ValuationCard
                compositeValue={valuation.compositeValue}
                currentPrice={valuation.currentPrice}
                discount={valuation.compositeDiscount}
                signal={valuation.signal}
              />
            )}
          </div>

          {/* Graham Criteria Breakdown */}
          {graham && (
            <>
              <h3 className="section-header">Graham Criteria Breakdown</h3>
              <div className="criteria-grid">
                {Object.entries(graham.details).map(([key, detail]) => (
                  <CriterionRow
                    key={key}
                    label={detail.label}
                    value={detail.value}
                    threshold={detail.threshold}
                    score={graham.scores[key]}
                  />
                ))}
              </div>
            </>
          )}

          {/* Fisher Checklist */}
          {fisher && (
            <>
              <h3 className="section-header">Fisher 15-Point Checklist</h3>
              <div className="criteria-grid">
                {Object.entries(fisher.details)
                  .sort((a, b) => (a[1].point || 0) - (b[1].point || 0))
                  .map(([key, detail]) => (
                    <CriterionRow
                      key={key}
                      label={`${detail.point}. ${detail.label}`}
                      value={detail.value}
                      threshold={detail.threshold}
                      score={fisher.scores[key] ?? 0}
                      manual={detail.manual}
                      question={detail.question}
                    />
                  ))}
              </div>
            </>
          )}

          {/* Valuation Models */}
          {valuation && (
            <>
              <h3 className="section-header">Valuation Models</h3>
              <div className="valuation-grid">
                {Object.entries(valuation.models).map(([key, model]) => (
                  <div key={key} className="val-model">
                    <div className="val-label">{model.label}</div>
                    <div className="val-price">{formatCurrency(model.intrinsicValue)}</div>
                    <div className="val-desc">{model.description}</div>
                    {model.discount != null && (
                      <div className={`val-discount ${model.discount > 0 ? 'positive' : 'negative'}`}>
                        {formatPercent(model.discount)} discount
                      </div>
                    )}
                    {model.inputs && (
                      <div style={{ marginTop: 8, fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        {Object.entries(model.inputs).map(([k, v]) => (
                          <div key={k}>{k}: {typeof v === 'number' ? v.toFixed(1) : v}</div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Buy Prices */}
          {valuation?.buyPrices && (
            <>
              <h3 className="section-header">Recommended Buy Prices</h3>
              <div className="buy-prices">
                <div className="buy-price-item">
                  <div className="mos-label">Current Price</div>
                  <div className="mos-price" style={{ color: 'var(--text-primary)' }}>
                    {formatCurrency(valuation.currentPrice)}
                  </div>
                </div>
                <div className="buy-price-item">
                  <div className="mos-label">25% Margin of Safety</div>
                  <div className="mos-price">{formatCurrency(valuation.buyPrices.mos25)}</div>
                </div>
                <div className="buy-price-item">
                  <div className="mos-label">35% Margin of Safety</div>
                  <div className="mos-price">{formatCurrency(valuation.buyPrices.mos35)}</div>
                </div>
                <div className="buy-price-item">
                  <div className="mos-label">50% Margin of Safety</div>
                  <div className="mos-price">{formatCurrency(valuation.buyPrices.mos50)}</div>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

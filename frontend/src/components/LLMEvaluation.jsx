import { useState, useEffect, useCallback } from 'react'
import { getLLMEvaluation, evaluateCompanyLLM, getLLMStatus } from '../utils/api'

// ----- small presentational helpers -----

const RISK_COLOR = {
  low: 'var(--green)', moderate: 'var(--amber)',
  elevated: 'var(--red)', high: 'var(--red)',
}
const DURABILITY_COLOR = {
  strong: 'var(--green)', moderate: 'var(--amber)', weak: 'var(--red)', none: 'var(--text-muted)',
}

function scoreColor(score) {
  if (score >= 4) return 'var(--green)'
  if (score === 3) return 'var(--amber)'
  if (score >= 1) return 'var(--red)'
  return 'var(--text-muted)'
}

function titleCase(s) {
  if (!s) return '—'
  return String(s).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// A compact 1-5 score card with a filled dot row.
function DimensionCard({ title, score, summary }) {
  const color = scoreColor(score)
  return (
    <div className="card" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', letterSpacing: 0.5, textTransform: 'uppercase' }}>{title}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span className="mono" style={{ fontSize: '1.6rem', fontWeight: 700, color }}>
          {score != null ? score : '—'}
        </span>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>/ 5</span>
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} style={{
            flex: 1, height: 4, borderRadius: 2,
            background: score != null && i <= score ? color : 'rgba(255,255,255,0.08)',
          }} />
        ))}
      </div>
      {summary && <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.45 }}>{summary}</p>}
    </div>
  )
}

function Badge({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontWeight: 700, color: color || 'var(--text-primary)', textTransform: 'capitalize' }}>
        {value || '—'}
      </div>
    </div>
  )
}

function BulletList({ items, color }) {
  if (!items || !items.length) return <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>—</div>
  return (
    <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {items.map((it, i) => (
        <li key={i} style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
          <span style={{ color }}>{it}</span>
        </li>
      ))}
    </ul>
  )
}

export default function LLMEvaluation({ symbol }) {
  const [evaluation, setEvaluation] = useState(null)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)     // running the LLM
  const [checking, setChecking] = useState(true)     // initial cache lookup
  const [error, setError] = useState('')

  // On symbol change: check for a cached evaluation + provider status. No LLM call.
  useEffect(() => {
    let cancelled = false
    setEvaluation(null)
    setError('')
    setChecking(true)
    ;(async () => {
      const [cached, st] = await Promise.allSettled([
        getLLMEvaluation(symbol),
        getLLMStatus(),
      ])
      if (cancelled) return
      if (cached.status === 'fulfilled') setEvaluation(cached.value)
      // A 404 (no cache) is expected and not an error.
      if (st.status === 'fulfilled') setStatus(st.value)
      setChecking(false)
    })()
    return () => { cancelled = true }
  }, [symbol])

  const runEvaluation = useCallback(async (force) => {
    setLoading(true)
    setError('')
    try {
      const result = await evaluateCompanyLLM(symbol, { force })
      setEvaluation(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [symbol])

  const meta = evaluation?._meta
  const comp = evaluation?.competitivePosition
  const earn = evaluation?.earningsQuality
  const cap = evaluation?.capitalAllocation
  const growth = evaluation?.growthOutlook
  const risk = evaluation?.riskAssessment
  const overall = evaluation?.overallAssessment
  const hasEval = evaluation && overall

  const providerNote = status
    ? (status.available
        ? `${titleCase(status.provider)} · ${status.model}`
        : `${titleCase(status.provider)} not configured`)
    : ''

  return (
    <>
      <h3 className="section-header">
        AI Qualitative Evaluation
        {meta && (
          <span style={{ marginLeft: 12, fontSize: '0.75rem', fontWeight: 500, color: 'var(--text-muted)' }}>
            {meta.model}{meta.cached ? ` · cached ${meta.cacheAgeDays ?? 0}d ago` : ' · fresh'}
          </span>
        )}
      </h3>

      <div className="card" style={{ padding: 16 }}>
        {/* Action bar */}
        <div className="controls" style={{ marginBottom: hasEval ? 16 : 0, alignItems: 'center' }}>
          {!hasEval && (
            <button
              className="btn btn-primary"
              onClick={() => runEvaluation(false)}
              disabled={loading || checking || (status && !status.available)}
            >
              {loading ? 'Evaluating…' : 'Evaluate with AI'}
            </button>
          )}
          {hasEval && (
            <button className="btn" onClick={() => runEvaluation(true)} disabled={loading}>
              {loading ? 'Re-evaluating…' : 'Re-run Evaluation'}
            </button>
          )}
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{providerNote}</span>
        </div>

        {status && !status.available && !hasEval && (
          <p style={{ fontSize: '0.82rem', color: 'var(--amber)', margin: '12px 0 0 0' }}>
            No LLM provider is configured. Set one up in the <strong>AI Settings</strong> tab first.
          </p>
        )}

        {checking && !hasEval && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            Checking for a saved evaluation…
          </div>
        )}

        {loading && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div className="loading-bars" style={{ justifyContent: 'center', marginBottom: 10 }}>
              <span /><span /><span /><span /><span />
            </div>
            Sending financials to the model — this can take 10–30 seconds.
          </div>
        )}

        {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}

        {evaluation?._missingSections?.length > 0 && (
          <p style={{ fontSize: '0.78rem', color: 'var(--amber)', marginTop: 8 }}>
            Note: the model omitted {evaluation._missingSections.join(', ')} — the response may be incomplete.
          </p>
        )}

        {/* Evaluation body */}
        {hasEval && !loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Overall banner */}
            <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', alignItems: 'center', paddingBottom: 12, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', letterSpacing: 0.5 }}>BUSINESS QUALITY</div>
                <div className="mono" style={{ fontSize: '1.8rem', fontWeight: 700, color: scoreColor(overall.qualityScore) }}>
                  {overall.qualityScore ?? '—'}<span style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}> / 5</span>
                </div>
              </div>
              <Badge label="OVERALL RISK" value={titleCase(risk?.overallRisk)} color={RISK_COLOR[risk?.overallRisk]} />
              <Badge label="MOAT" value={titleCase(comp?.moatType)} />
              <Badge label="MOAT DURABILITY" value={titleCase(comp?.moatDurability)} color={DURABILITY_COLOR[comp?.moatDurability]} />
              <Badge label="CONFIDENCE" value={titleCase(overall?.confidenceLevel)} />
              {overall.oneLineSummary && (
                <div style={{ flex: 1, minWidth: 240, fontStyle: 'italic', color: 'var(--text-secondary)', fontSize: '0.88rem' }}>
                  “{overall.oneLineSummary}”
                </div>
              )}
            </div>

            {/* 5 dimension score cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
              <DimensionCard title="Competitive Position" score={comp?.score} summary={comp?.summary} />
              <DimensionCard title="Earnings Quality" score={earn?.score} summary={earn?.summary} />
              <DimensionCard title="Capital Allocation" score={cap?.score} summary={cap?.summary} />
              <DimensionCard title="Growth Outlook" score={growth?.score} summary={growth?.summary} />
              <DimensionCard title="Risk" score={risk?.score} summary={risk?.summary} />
            </div>

            {/* Strengths / Weaknesses / Risks */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--green)', fontWeight: 600, marginBottom: 8 }}>STRENGTHS</div>
                <BulletList items={overall.strengthsTopThree} color="var(--text-secondary)" />
              </div>
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--red)', fontWeight: 600, marginBottom: 8 }}>WEAKNESSES</div>
                <BulletList items={overall.weaknessesTopThree} color="var(--text-secondary)" />
              </div>
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--amber)', fontWeight: 600, marginBottom: 8 }}>KEY RISKS</div>
                <BulletList items={risk?.keyRisks} color="var(--text-secondary)" />
              </div>
            </div>

            {/* Extra qualitative detail chips */}
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              {earn?.cashFlowAlignment && <span>Cash-flow alignment: <strong style={{ color: 'var(--text-secondary)' }}>{titleCase(earn.cashFlowAlignment)}</strong></span>}
              {cap?.debtManagement && <span>Debt mgmt: <strong style={{ color: 'var(--text-secondary)' }}>{titleCase(cap.debtManagement)}</strong></span>}
              {cap?.shareholderReturns && <span>Shareholder returns: <strong style={{ color: 'var(--text-secondary)' }}>{titleCase(cap.shareholderReturns)}</strong></span>}
              {growth?.revenueTrajectory && <span>Revenue: <strong style={{ color: 'var(--text-secondary)' }}>{titleCase(growth.revenueTrajectory)}</strong></span>}
              {growth?.marginTrajectory && <span>Margins: <strong style={{ color: 'var(--text-secondary)' }}>{titleCase(growth.marginTrajectory)}</strong></span>}
              {risk?.cyclicality && <span>Cyclicality: <strong style={{ color: 'var(--text-secondary)' }}>{titleCase(risk.cyclicality)}</strong></span>}
            </div>

            <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: 0, fontStyle: 'italic' }}>
              AI-generated qualitative assessment, not financial advice. {meta?.cached ? 'Cached result — use "Re-run" for a fresh evaluation.' : ''}
            </p>
          </div>
        )}
      </div>
    </>
  )
}

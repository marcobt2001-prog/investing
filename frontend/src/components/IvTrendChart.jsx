import { useMemo } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend,
} from 'recharts'

// Colors per series. Composite + price are emphasized; models are muted.
const SERIES = [
  { key: 'avg_price', name: 'Stock Price', color: '#e2e8f0', width: 2.5, dash: null },
  { key: 'composite', name: 'Composite IV', color: '#3b82f6', width: 2.5, dash: null },
  { key: 'graham', name: 'Graham', color: '#22c55e', width: 1, dash: '4 3' },
  { key: 'dcf', name: 'DCF', color: '#f59e0b', width: 1, dash: '4 3' },
  { key: 'book_value', name: 'Book Value', color: '#a855f7', width: 1, dash: '4 3' },
  { key: 'epv', name: 'EPV', color: '#06b6d4', width: 1, dash: '4 3' },
  { key: 'ncav', name: 'NCAV', color: '#ef4444', width: 1, dash: '4 3' },
]

/**
 * IV-vs-price line chart. Expects an `ivTrends` object with:
 *   history: [{ fiscal_year, composite, avg_price }]
 *   modelHistory: { graham: [...], dcf: [...], ... } aligned to history order
 */
export default function IvTrendChart({ ivTrends }) {
  const chartData = useMemo(() => {
    if (!ivTrends?.history?.length) return []
    const mh = ivTrends.modelHistory || {}
    return ivTrends.history.map((h, i) => ({
      year: h.fiscal_year,
      avg_price: h.avg_price,
      composite: h.composite,
      graham: mh.graham?.[i] ?? null,
      dcf: mh.dcf?.[i] ?? null,
      book_value: mh.book_value?.[i] ?? null,
      epv: mh.epv?.[i] ?? null,
      ncav: mh.ncav?.[i] ?? null,
    }))
  }, [ivTrends])

  if (!chartData.length) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
        No historical valuation data available for this company.
      </div>
    )
  }

  return (
    <div style={{ width: '100%', height: 380 }}>
      <ResponsiveContainer>
        <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis dataKey="year" stroke="var(--text-muted)" fontSize={12} />
          <YAxis
            stroke="var(--text-muted)"
            fontSize={12}
            tickFormatter={(v) => `$${v}`}
            width={56}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--bg-elevated, #1a1f2e)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: 'var(--text-primary)' }}
            formatter={(value, name) => [value != null ? `$${Number(value).toFixed(2)}` : '—', name]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {SERIES.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.name}
              stroke={s.color}
              strokeWidth={s.width}
              strokeDasharray={s.dash || undefined}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

import { useState, useCallback } from 'react'
import { searchStocks } from '../utils/api'
import { formatCurrency, formatLargeCurrency, formatVolume, formatRatio } from '../utils/format'

const SECTORS = [
  'All Sectors',
  'Technology',
  'Healthcare',
  'Financial Services',
  'Consumer Defensive',
  'Consumer Cyclical',
  'Industrials',
  'Energy',
  'Utilities',
  'Real Estate',
  'Basic Materials',
  'Communication Services',
]

const CAP_RANGES = [
  { label: 'All Caps', min: '', max: '' },
  { label: 'Mega (>$200B)', min: '200000000000', max: '' },
  { label: 'Large ($10B-$200B)', min: '10000000000', max: '200000000000' },
  { label: 'Mid ($2B-$10B)', min: '2000000000', max: '10000000000' },
  { label: 'Small ($300M-$2B)', min: '300000000', max: '2000000000' },
  { label: 'Micro (<$300M)', min: '', max: '300000000' },
]

// Curated stock universe matching the backend
const STOCK_UNIVERSE = {
  'Technology': ['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META', 'AVGO', 'ORCL', 'CRM', 'AMD', 'INTC',
    'ADBE', 'CSCO', 'TXN', 'QCOM', 'IBM', 'NOW', 'INTU', 'AMAT', 'MU', 'LRCX'],
  'Healthcare': ['JNJ', 'UNH', 'PFE', 'ABBV', 'MRK', 'LLY', 'TMO', 'ABT', 'DHR', 'BMY',
    'AMGN', 'MDT', 'GILD', 'ISRG', 'CVS', 'ELV', 'SYK', 'ZTS', 'VRTX', 'BDX'],
  'Financial Services': ['JPM', 'BAC', 'WFC', 'GS', 'MS', 'BLK', 'SCHW', 'C', 'AXP', 'USB',
    'PNC', 'TFC', 'BK', 'CME', 'ICE', 'AON', 'MMC', 'CB', 'MET', 'AIG'],
  'Consumer Defensive': ['PG', 'KO', 'PEP', 'WMT', 'COST', 'PM', 'MO', 'CL', 'MDLZ', 'GIS',
    'KMB', 'SYY', 'K', 'HSY', 'TSN', 'CAG', 'CPB', 'SJM', 'KHC', 'HRL'],
  'Consumer Cyclical': ['AMZN', 'TSLA', 'HD', 'NKE', 'MCD', 'SBUX', 'LOW', 'TJX', 'BKNG', 'MAR',
    'GM', 'F', 'LULU', 'CMG', 'YUM', 'DPZ', 'EBAY', 'ETSY', 'BBY', 'DHI'],
  'Industrials': ['CAT', 'HON', 'UPS', 'RTX', 'BA', 'GE', 'DE', 'LMT', 'MMM', 'UNP',
    'WM', 'ETN', 'ITW', 'EMR', 'FDX', 'NSC', 'CSX', 'GD', 'NOC', 'TT'],
  'Energy': ['XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'PSX', 'VLO', 'OXY', 'PXD',
    'HES', 'DVN', 'HAL', 'BKR', 'FANG', 'WMB', 'KMI', 'OKE', 'TRGP', 'LNG'],
  'Utilities': ['NEE', 'DUK', 'SO', 'D', 'AEP', 'SRE', 'EXC', 'XEL', 'ED', 'WEC',
    'ES', 'AWK', 'DTE', 'PPL', 'FE', 'EIX', 'AEE', 'CMS', 'CNP', 'ATO'],
  'Real Estate': ['AMT', 'PLD', 'CCI', 'EQIX', 'PSA', 'SPG', 'O', 'WELL', 'DLR', 'AVB',
    'EQR', 'VTR', 'ARE', 'MAA', 'UDR', 'ESS', 'PEAK', 'HST', 'KIM', 'REG'],
  'Basic Materials': ['LIN', 'APD', 'SHW', 'ECL', 'FCX', 'NEM', 'NUE', 'DD', 'DOW', 'PPG',
    'VMC', 'MLM', 'ALB', 'CE', 'EMN', 'FMC', 'CF', 'MOS', 'IFF', 'RPM'],
  'Communication Services': ['GOOG', 'DIS', 'CMCSA', 'NFLX', 'T', 'VZ', 'TMUS', 'CHTR', 'EA', 'ATVI',
    'TTWO', 'MTCH', 'ZM', 'SNAP', 'PINS', 'ROKU', 'PARA', 'WBD', 'LYV', 'OMC'],
}

export default function Screener({ apiKey, onSelectStock }) {
  const [sector, setSector] = useState('All Sectors')
  const [capRange, setCapRange] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hasSearched, setHasSearched] = useState(false)

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return
    setLoading(true)
    setError('')
    try {
      const results = await searchStocks(apiKey, searchQuery)
      setSearchResults(results)
      setHasSearched(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [apiKey, searchQuery])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSearch()
  }

  // Get stocks from curated list based on sector
  const getDisplayStocks = () => {
    if (sector === 'All Sectors') {
      let all = []
      for (const syms of Object.values(STOCK_UNIVERSE)) {
        all = all.concat(syms.slice(0, 5))
      }
      return all
    }
    return STOCK_UNIVERSE[sector] || []
  }

  const displayStocks = getDisplayStocks()

  return (
    <div>
      {/* Search bar */}
      <div className="controls">
        <input
          type="text"
          placeholder="Search by company name or ticker..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          style={{ flex: 1, minWidth: 200 }}
        />
        <button className="btn btn-primary" onClick={handleSearch} disabled={loading || !searchQuery.trim()}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {/* Search results */}
      {hasSearched && searchResults.length > 0 && (
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
      {hasSearched && searchResults.length === 0 && !loading && (
        <div className="card" style={{ marginBottom: 24, padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
          No results found for "{searchQuery}"
        </div>
      )}

      {/* Sector browser */}
      <h3 className="section-header">Browse by Sector</h3>
      <div className="controls">
        <select value={sector} onChange={(e) => setSector(e.target.value)}>
          {SECTORS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
          {displayStocks.length} stocks {sector !== 'All Sectors' ? `in ${sector}` : 'across all sectors'}
        </span>
      </div>

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Sector</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {displayStocks.map((sym) => (
              <tr key={sym} className="clickable" onClick={() => onSelectStock(sym)}>
                <td className="mono" style={{ color: 'var(--green)', fontWeight: 600 }}>{sym}</td>
                <td style={{ color: 'var(--text-muted)' }}>{sector === 'All Sectors' ? '' : sector}</td>
                <td style={{ color: 'var(--blue)', cursor: 'pointer' }}>Analyze →</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p style={{ marginTop: 16, fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
        Click any stock to run a full Graham + Fisher analysis with valuation models.
        Use search to find stocks not in the curated list.
      </p>
    </div>
  )
}

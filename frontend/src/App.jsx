import { useState, useCallback } from 'react'
import './App.css'
import Screener from './components/Screener'
import Analysis from './components/Analysis'
import Backtest from './components/Backtest'

function App() {
  const [apiKey, setApiKey] = useState('')
  const [activeTab, setActiveTab] = useState('screener')
  const [selectedSymbol, setSelectedSymbol] = useState('')

  const handleSelectStock = useCallback((symbol) => {
    setSelectedSymbol(symbol)
    setActiveTab('analysis')
  }, [])

  const handleBacktestStock = useCallback((symbol) => {
    setSelectedSymbol(symbol)
    setActiveTab('backtest')
  }, [])

  return (
    <>
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <h1 className="header-title">Value Investor</h1>
          <span className="header-subtitle">Intelligence System</span>
        </div>
        <div className="api-key-input">
          <label>FMP API Key</label>
          <input
            type="password"
            placeholder="Enter your API key..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <span className={`key-status ${apiKey ? 'valid' : 'empty'}`}>
            {apiKey ? 'Ready' : 'Required'}
          </span>
        </div>
      </header>

      {/* Tabs */}
      <nav className="tabs">
        <button
          className={`tab ${activeTab === 'screener' ? 'active' : ''}`}
          onClick={() => setActiveTab('screener')}
        >
          Screener
        </button>
        <button
          className={`tab ${activeTab === 'analysis' ? 'active' : ''}`}
          onClick={() => setActiveTab('analysis')}
        >
          Analysis
        </button>
        <button
          className={`tab ${activeTab === 'backtest' ? 'active' : ''}`}
          onClick={() => setActiveTab('backtest')}
        >
          Backtest
        </button>
      </nav>

      {/* Content */}
      {!apiKey ? (
        <div className="empty-state">
          <h3>Enter Your API Key</h3>
          <p>
            Enter your Financial Modeling Prep API key above to get started.
            Get a free key at{' '}
            <a href="https://financialmodelingprep.com/developer" target="_blank" rel="noreferrer"
               style={{ color: 'var(--blue)' }}>
              financialmodelingprep.com
            </a>
          </p>
        </div>
      ) : (
        <div className="fade-in" key={activeTab}>
          {activeTab === 'screener' && (
            <Screener apiKey={apiKey} onSelectStock={handleSelectStock} />
          )}
          {activeTab === 'analysis' && (
            <Analysis
              apiKey={apiKey}
              initialSymbol={selectedSymbol}
              onBacktest={handleBacktestStock}
            />
          )}
          {activeTab === 'backtest' && (
            <Backtest apiKey={apiKey} initialSymbol={selectedSymbol} />
          )}
        </div>
      )}

      {/* Disclaimer */}
      <footer className="disclaimer">
        This tool is for educational and research purposes only. It is not financial advice.
        Always do your own research and consult a qualified financial advisor before making investment decisions.
      </footer>
    </>
  )
}

export default App

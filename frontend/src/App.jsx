import { useState, useCallback } from 'react'
import './App.css'
import Screener from './components/Screener'
import Analysis from './components/Analysis'
import Backtest from './components/Backtest'
import IndustryView from './components/IndustryView'
import LLMSettings from './components/LLMSettings'

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
          <label>FMP API Key (optional)</label>
          <input
            type="password"
            placeholder="Only needed as fallback..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <span className={`key-status ${apiKey ? 'valid' : 'empty'}`}>
            {apiKey ? 'Set' : 'DB-only'}
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
          className={`tab ${activeTab === 'industries' ? 'active' : ''}`}
          onClick={() => setActiveTab('industries')}
        >
          Industries
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
        <button
          className={`tab ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => setActiveTab('settings')}
        >
          AI Settings
        </button>
      </nav>

      {/* Content — works without an API key. The key is only forwarded
          to /api/analyze and /api/backtest as an FMP fallback for tickers
          not yet in the local DB. */}
      <div className="fade-in" key={activeTab}>
        {activeTab === 'screener' && (
          <Screener apiKey={apiKey} onSelectStock={handleSelectStock} />
        )}
        {activeTab === 'industries' && (
          <IndustryView onSelectStock={handleSelectStock} />
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
        {activeTab === 'settings' && (
          <LLMSettings />
        )}
      </div>

      {/* Disclaimer */}
      <footer className="disclaimer">
        This tool is for educational and research purposes only. It is not financial advice.
        Always do your own research and consult a qualified financial advisor before making investment decisions.
      </footer>
    </>
  )
}

export default App

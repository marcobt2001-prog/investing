import { useState, useEffect, useCallback } from 'react'
import { getLLMStatus, configureLLM } from '../utils/api'

// Current Claude tiers. claude-sonnet-5 is the sensible default (near-Opus
// quality at Sonnet cost); Opus for the deepest analysis, Haiku for cheap/fast.
const CLAUDE_MODELS = [
  { id: 'claude-sonnet-5', label: 'Sonnet 5 (recommended — balanced)' },
  { id: 'claude-opus-4-8', label: 'Opus 4.8 (most capable)' },
  { id: 'claude-haiku-4-5', label: 'Haiku 4.5 (fast & cheap)' },
]

// Common local Ollama models. The field is free-text too, so any pulled
// model name works.
const OLLAMA_MODELS = ['llama3.1:8b', 'llama3.1:70b', 'mistral', 'mixtral', 'phi3', 'qwen2.5:14b']

function StatusPill({ available }) {
  const color = available ? 'var(--green)' : 'var(--red)'
  const label = available ? 'Available' : 'Not available'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', color }}>
      <span style={{ width: 9, height: 9, borderRadius: '50%', background: color, display: 'inline-block' }} />
      {label}
    </span>
  )
}

export default function LLMSettings() {
  const [status, setStatus] = useState(null)
  const [provider, setProvider] = useState('claude')
  const [claudeApiKey, setClaudeApiKey] = useState('')
  const [claudeModel, setClaudeModel] = useState('claude-sonnet-5')
  const [ollamaModel, setOllamaModel] = useState('llama3.1:8b')
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState('http://localhost:11434')

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getLLMStatus()
      setStatus(s)
      // Sync form fields from the server (but never the key — it's never returned).
      setProvider(s.provider || 'claude')
      if (s.claudeModel) setClaudeModel(s.claudeModel)
      if (s.ollamaModel) setOllamaModel(s.ollamaModel)
      if (s.ollamaBaseUrl) setOllamaBaseUrl(s.ollamaBaseUrl)
      return s
    } catch (e) {
      setError(e.message)
      return null
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      await refreshStatus()
      if (!cancelled) setLoading(false)
    })()
    return () => { cancelled = true }
  }, [refreshStatus])

  const handleSave = async () => {
    setSaving(true)
    setMsg('')
    setError('')
    try {
      const payload = { provider }
      if (provider === 'claude') {
        payload.claudeModel = claudeModel
        // Only send the key if the user typed one — a blank field must NOT
        // wipe a previously-saved key (the backend preserves it on empty).
        if (claudeApiKey.trim()) payload.claudeApiKey = claudeApiKey.trim()
      } else {
        payload.ollamaModel = ollamaModel
        payload.ollamaBaseUrl = ollamaBaseUrl
      }
      const s = await configureLLM(payload)
      setStatus(s)
      setClaudeApiKey('') // clear the input; the key is now stored server-side
      setMsg(
        s.available
          ? `Saved. ${s.provider === 'claude' ? 'Claude' : 'Ollama'} is ready (${s.model}).`
          : `Saved, but the provider is not available yet.${
              s.provider === 'claude'
                ? (s.hasApiKey ? ' Check that the API key is valid.' : ' Add an API key.')
                : ' Is Ollama running and the model pulled?'
            }`
      )
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setMsg('')
    setError('')
    const s = await refreshStatus()
    if (s) {
      setMsg(
        s.available
          ? `Connection OK — ${s.provider} (${s.model}) is available.`
          : `${s.provider} (${s.model}) is not available. ${
              s.provider === 'claude'
                ? (s.hasApiKey ? 'The stored key may be invalid.' : 'No API key is set.')
                : 'Ensure Ollama is running and the model is pulled.'
            }`
      )
    }
  }

  if (loading) {
    return <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>Loading LLM settings…</div>
  }

  return (
    <div style={{ maxWidth: 680 }}>
      {/* Current status */}
      <div className="card" style={{ padding: 16, marginBottom: 16, display: 'flex', gap: 32, flexWrap: 'wrap', alignItems: 'center' }}>
        <div>
          <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>ACTIVE PROVIDER</span>
          <div className="mono" style={{ fontSize: '1.1rem', textTransform: 'capitalize' }}>{status?.provider || '—'}</div>
        </div>
        <div>
          <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>MODEL</span>
          <div className="mono" style={{ fontSize: '1.1rem' }}>{status?.model || '—'}</div>
        </div>
        <div>
          <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>STATUS</span>
          <div style={{ marginTop: 4 }}><StatusPill available={!!status?.available} /></div>
        </div>
        {status?.provider === 'claude' && (
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>API KEY</span>
            <div className="mono" style={{ fontSize: '0.95rem', color: status?.hasApiKey ? 'var(--green)' : 'var(--amber)' }}>
              {status?.hasApiKey ? 'Set' : 'Not set'}
            </div>
          </div>
        )}
      </div>

      {/* Provider toggle */}
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 className="card-header">Provider</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {['claude', 'ollama'].map((p) => (
            <button
              key={p}
              className={`btn ${provider === p ? 'btn-primary' : ''}`}
              onClick={() => setProvider(p)}
              style={{ textTransform: 'capitalize', flex: 1 }}
            >
              {p === 'claude' ? 'Claude API' : 'Ollama (local)'}
            </button>
          ))}
        </div>

        {provider === 'claude' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              ANTHROPIC API KEY {status?.hasApiKey && <span style={{ color: 'var(--green)' }}>(a key is already stored — leave blank to keep it)</span>}
              <input
                type="password"
                placeholder={status?.hasApiKey ? '•••••••• (stored)' : 'sk-ant-...'}
                value={claudeApiKey}
                onChange={(e) => setClaudeApiKey(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              MODEL
              <select value={claudeModel} onChange={(e) => setClaudeModel(e.target.value)}>
                {CLAUDE_MODELS.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            </label>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: 0 }}>
              Your key is stored locally in <span className="mono">backend/llm_config.json</span> and only sent to Anthropic. It is never returned to the browser.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              MODEL
              <input
                list="ollama-models"
                value={ollamaModel}
                onChange={(e) => setOllamaModel(e.target.value)}
                placeholder="llama3.1:8b"
              />
              <datalist id="ollama-models">
                {OLLAMA_MODELS.map((m) => <option key={m} value={m} />)}
              </datalist>
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              BASE URL
              <input
                value={ollamaBaseUrl}
                onChange={(e) => setOllamaBaseUrl(e.target.value)}
                placeholder="http://localhost:11434"
              />
            </label>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: 0 }}>
              Runs fully local — no API key, no data leaves your machine. Requires{' '}
              <a href="https://ollama.com" target="_blank" rel="noreferrer" style={{ color: 'var(--blue)' }}>Ollama</a>{' '}
              running with the model pulled (<span className="mono">ollama pull {ollamaModel || 'llama3.1:8b'}</span>).
            </p>
          </div>
        )}

        <div className="controls" style={{ marginTop: 16, marginBottom: 0 }}>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
          <button className="btn" onClick={handleTest} disabled={saving}>
            Test Connection
          </button>
        </div>
      </div>

      {msg && (
        <div className="card" style={{ padding: '10px 16px', marginBottom: 12, color: 'var(--text-secondary)' }}>{msg}</div>
      )}
      {error && <div className="error-msg">{error}</div>}
    </div>
  )
}

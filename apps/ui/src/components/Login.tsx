import { useState } from 'react'

export function Login({ onLogin, error }: { onLogin: (key: string) => void; error?: string }) {
  const [key, setKey] = useState('')
  return (
    <div className="login">
      <form className="panel" onSubmit={e => { e.preventDefault(); onLogin(key.trim()) }}>
        <div className="panel-h"><span className="brand">HEREN AGENT</span><span className="count">control</span></div>
        <div className="panel-b">
          <label className="dim mono" style={{ fontSize: 11 }}>API KEY</label>
          <input className="input" type="password" autoFocus value={key} onChange={e => setKey(e.target.value)} placeholder="HEREN_API_KEY" />
          {error && <div className="err-line">{error}</div>}
          <div style={{ marginTop: 10 }}><button className="btn primary" type="submit" disabled={!key.trim()}>Bağlan</button></div>
        </div>
      </form>
    </div>
  )
}

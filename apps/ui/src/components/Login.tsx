import { useState } from 'react'

interface Props { onLogin: (key: string, remember: boolean) => void; error?: string }

export function Login({ onLogin, error }: Props) {
  const [key, setKey] = useState('')
  const [remember, setRemember] = useState(false)
  return (
    <div className="login">
      <form className="panel" onSubmit={e => { e.preventDefault(); onLogin(key.trim(), remember) }}>
        <div className="panel-h"><span className="brand">HEREN AGENT</span><span className="count">control</span></div>
        <div className="panel-b">
          <label className="dim mono" style={{ fontSize: 11 }} htmlFor="login-key">API KEY</label>
          <input id="login-key" className="input" type="password" autoFocus value={key} onChange={e => setKey(e.target.value)} placeholder="HEREN_API_KEY" />
          <label className="check">
            <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
            Bu cihazda beni hatırla (30 gün)
          </label>
          {error && <div className="err-line">{error}</div>}
          <div style={{ marginTop: 10 }}><button className="btn primary" type="submit" disabled={!key.trim()}>Bağlan</button></div>
        </div>
      </form>
    </div>
  )
}

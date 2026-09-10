import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { Api, ApiError, connectEvents } from './lib/api'
import { initialState, reduce } from './lib/store'
import type { AuditRow, BootEntry } from './lib/types'
import { Approvals } from './components/Approvals'
import { CharacterPanel } from './components/CharacterPanel'
import { Conversation } from './components/Conversation'
import { DeviceCard } from './components/DeviceCard'
import { Login } from './components/Login'
import { Activity, Audit } from './components/Logs'
import { PairingModal } from './components/PairingModal'

const KEY_STORAGE = 'heren.api_key'
const APPROVER = 'ui:dashboard'

export default function App() {
  const [key, setKey] = useState<string | null>(() => sessionStorage.getItem(KEY_STORAGE))
  const [loginError, setLoginError] = useState<string>()

  const login = async (k: string) => {
    try {
      await new Api(k).devices()
      sessionStorage.setItem(KEY_STORAGE, k)
      setLoginError(undefined)
      setKey(k)
    } catch (e) {
      setLoginError(e instanceof ApiError && e.status === 401 ? 'geçersiz anahtar' : `bağlantı hatası: ${(e as Error).message}`)
    }
  }
  if (!key) return <Login onLogin={login} error={loginError} />
  return <Dashboard apiKey={key} onLogout={() => { sessionStorage.removeItem(KEY_STORAGE); setKey(null) }} />
}

function Dashboard({ apiKey, onLogout }: { apiKey: string; onLogout: () => void }) {
  const api = useMemo(() => new Api(apiKey), [apiKey])
  const [state, dispatch] = useReducer(reduce, initialState)
  const [boot, setBoot] = useState<Record<string, BootEntry[]>>({})
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [tab, setTab] = useState<'activity' | 'audit'>('activity')
  const [pairing, setPairing] = useState(false)
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)
  const toastTimer = useRef<number>(0)

  const say = useCallback((text: string, err = false) => {
    setToast({ text, err })
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 4000)
  }, [])

  useEffect(() => connectEvents(apiKey, dispatch), [apiKey])

  const loadAudit = useCallback(() => api.audit(100).then(setAudit).catch(() => {}), [api])
  useEffect(() => { if (tab === 'audit') loadAudit() }, [tab, loadAudit, state.activity.length])

  const onAction = useCallback(async (deviceId: string, action: string, params: Record<string, unknown>) => {
    try {
      const res = await api.submit(deviceId, action, params)
      if (res.status === 'awaiting_approval') say(`${action}: onay bekliyor`)
      else if (res.status === 'completed') {
        if (action === 'get_boot_entries') setBoot(b => ({ ...b, [deviceId]: (res.output.entries as BootEntry[]) ?? [] }))
        say(`${action}: tamam${action === 'get_status' ? ' · ' + JSON.stringify(res.output) : ''}`)
      } else say(`${action}: ${res.status}${res.error ? ' — ' + res.error : ''}`, true)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onLogout()
      else say(`${action}: ${(e as Error).message}`, true)
    }
  }, [api, say, onLogout])

  const onApprove = useCallback(async (id: string) => {
    try { const r = await api.approve(id, APPROVER); say(`onaylandı → ${r.status}${r.error ? ' — ' + r.error : ''}`, r.status !== 'completed') }
    catch (e) { say(`onay hatası: ${(e as Error).message}`, true) }
  }, [api, say])
  const onDeny = useCallback(async (id: string) => {
    try { await api.deny(id, APPROVER); say('reddedildi') }
    catch (e) { say(`ret hatası: ${(e as Error).message}`, true) }
  }, [api, say])

  const devices = Object.values(state.devices).sort((a, b) => a.name.localeCompare(b.name))
  const names = Object.fromEntries(devices.map(d => [d.device_id, d.name]))
  const online = devices.filter(d => d.status === 'online').length
  const fetchCode = useCallback(() => api.pairingCode(), [api])
  const onTouch = useCallback(() => { api.touch().catch(e => say(`dokunma: ${(e as Error).message}`, true)) }, [api, say])
  const onAsk = useCallback((text: string) => { api.ask(text).catch(e => say(`soru: ${(e as Error).message}`, true)) }, [api, say])

  return (
    <div className="shell">
      <div className="topbar">
        <span className="brand">HEREN AGENT</span>
        <span className="dim mono" style={{ fontSize: 11 }}>{online}/{devices.length} online</span>
        <span className="spacer" />
        <button className="btn" onClick={() => setPairing(true)}>+ Cihaz eşle</button>
        <button className="btn" onClick={onLogout}>Çıkış</button>
      </div>
      <div className="main">
        <div className="col">
          {devices.length === 0 && <div className="empty">cihaz yok — "+ Cihaz eşle" ile başla</div>}
          <div className="devices">
            {devices.map(d => (
              <DeviceCard key={d.device_id} device={d} metrics={state.metrics[d.device_id] ?? {}}
                bootEntries={boot[d.device_id]} onAction={onAction} />
            ))}
          </div>
          <Conversation rows={state.conversation} hermes={state.hermes} onAsk={onAsk} />
        </div>
        <div>
          <CharacterPanel state={state.character} onTouch={onTouch} />
          <Approvals approvals={state.approvals} devices={state.devices} onApprove={onApprove} onDeny={onDeny} />
          <div className="panel">
            <div className="panel-h">
              <button className={`btn ${tab === 'activity' ? 'primary' : ''}`} onClick={() => setTab('activity')}>Etkinlik</button>
              <button className={`btn ${tab === 'audit' ? 'primary' : ''}`} onClick={() => setTab('audit')}>Denetim</button>
            </div>
          </div>
          {tab === 'activity' ? <Activity rows={state.activity} deviceNames={names} /> : <Audit rows={audit} deviceNames={names} />}
        </div>
      </div>
      <div className="statusbar">
        <span style={{ color: state.connected ? 'var(--ok)' : 'var(--accent)' }}>● {state.connected ? 'core bağlı' : 'core bağlantısı yok'}</span>
        <span>onay bekleyen: {state.approvals.length}</span>
        <span>heren: {state.character.activity}/{state.character.mood}</span>
      </div>
      {pairing && <PairingModal fetchCode={fetchCode} onClose={() => setPairing(false)} />}
      {toast && <div className={`toast ${toast.err ? 'err' : ''}`}>{toast.text}</div>}
    </div>
  )
}

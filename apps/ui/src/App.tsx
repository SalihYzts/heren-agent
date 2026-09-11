import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { Api, ApiError, connectEvents } from './lib/api'
import { initialState, reduce } from './lib/store'
import { applyTheme, loadSettings, packForLook, saveSettings, type Settings } from './lib/settings'
import type { AuditRow, BootEntry } from './lib/types'
import { Approvals } from './components/Approvals'
import { CharacterPanel } from './components/CharacterPanel'
import { Conversation } from './components/Conversation'
import { DeviceCard } from './components/DeviceCard'
import { Login } from './components/Login'
import { Activity, Audit } from './components/Logs'
import { PairingModal } from './components/PairingModal'
import { QuickActions } from './components/QuickActions'
import { ServerControls, ACTION_LABEL } from './components/ServerControls'
import { SettingsView } from './components/SettingsView'
import { VoiceBar } from './components/VoiceBar'
import { Vitals } from './components/Vitals'
import { ServicesView } from './components/ServicesView'
import type { Sample } from './lib/api'
import { useVoice } from './voice/useVoice'
import { clearSession, loadSession, saveSession } from './lib/session'

const APPROVER = 'ui:dashboard'
type View = 'home' | 'services' | 'devices' | 'logs' | 'settings'

export default function App() {
  const [key, setKey] = useState<string | null>(() => loadSession())
  const [loginError, setLoginError] = useState<string>()
  const [settings, setSettings] = useState<Settings>(loadSettings)
  useEffect(() => { applyTheme(settings.theme) }, [settings.theme])
  const changeSettings = (s: Settings) => { setSettings(s); saveSettings(s) }

  const login = async (k: string, remember: boolean) => {
    try {
      await new Api(k).devices()
      saveSession(k, remember)
      setLoginError(undefined)
      setKey(k)
    } catch (e) {
      setLoginError(e instanceof ApiError && e.status === 401 ? 'geçersiz anahtar' : `bağlantı hatası: ${(e as Error).message}`)
    }
  }
  if (!key) return <Login onLogin={login} error={loginError} />
  return <Dashboard apiKey={key} settings={settings} onSettings={changeSettings}
    onLogout={() => { clearSession(); setKey(null) }} />
}

interface DashProps { apiKey: string; settings: Settings; onSettings: (s: Settings) => void; onLogout: () => void }

function Dashboard({ apiKey, settings, onSettings, onLogout }: DashProps) {
  const api = useMemo(() => new Api(apiKey), [apiKey])
  const [state, dispatch] = useReducer(reduce, initialState)
  const [boot, setBoot] = useState<Record<string, BootEntry[]>>({})
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [tab, setTab] = useState<'activity' | 'audit'>('activity')
  const [view, setView] = useState<View>('home')
  const [showApprovals, setShowApprovals] = useState(false)
  const [pairing, setPairing] = useState(false)
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)
  const toastTimer = useRef<number>(0)

  const say = useCallback((text: string, err = false) => {
    setToast({ text, err })
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 4000)
  }, [])

  const choice = useMemo(() => ({ model: settings.model, provider: settings.provider }), [settings.model, settings.provider])
  const voice = useVoice(api, undefined, choice)
  const onEvent = useCallback((e: Parameters<typeof dispatch>[0]) => { dispatch(e); voice.handleEvent(e) }, [voice.handleEvent])
  useEffect(() => connectEvents(apiKey, onEvent), [apiKey, onEvent])

  const loadAudit = useCallback(() => api.audit(100).then(setAudit).catch(() => {}), [api])
  useEffect(() => { if (view === 'logs' && tab === 'audit') loadAudit() }, [view, tab, loadAudit, state.activity.length])

  const onAction = useCallback(async (deviceId: string, action: string, params: Record<string, unknown>) => {
    const label = ACTION_LABEL[action] ?? action
    try {
      const res = await api.submit(deviceId, action, params)
      if (res.status === 'awaiting_approval') say(`${label}: onay bekliyor`)
      else if (res.status === 'completed') {
        if (action === 'get_boot_entries') setBoot(b => ({ ...b, [deviceId]: (res.output.entries as BootEntry[]) ?? [] }))
        say(`${label}: tamam${action === 'get_status' ? ' · ' + JSON.stringify(res.output) : ''}`)
      } else say(`${label}: ${res.status}${res.error ? ' — ' + res.error : ''}`, true)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onLogout()
      else say(`${label}: ${(e as Error).message}`, true)
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

  const paired = Object.values(state.devices)                 // pairing order (first paired = the server by default)
  const devices = [...paired].sort((a, b) => a.name.localeCompare(b.name))
  const names = Object.fromEntries(devices.map(d => [d.device_id, d.name]))
  const serverId = settings.server && state.devices[settings.server] ? settings.server : paired[0]?.device_id

  const fetchCode = useCallback(() => api.pairingCode(), [api])
  // server vitals history (sparklines): refetch when the server changes or a new sample lands (cheap, ≤ every 30 s)
  const [history, setHistory] = useState<Sample[]>([])
  const latestTs = serverId ? state.metrics[serverId]?.ts : undefined
  useEffect(() => {
    if (!serverId) return
    let on = true
    api.metricsHistory(serverId, 3600).then(h => { if (on) setHistory(h) }).catch(() => {})
    return () => { on = false }
  }, [api, serverId, latestTs])
  // services view runs actions and needs their output back (not just a toast)
  const runForOutput = useCallback(async (deviceId: string, action: string, params: Record<string, unknown>) => {
    const res = await api.submit(deviceId, action, params)
    if (res.status !== 'completed') throw new Error(res.error ?? res.status)
    return res.output
  }, [api])
  // Tapping Heren = wake/attention on the core AND open the mic (tap again to send).
  const onTouch = useCallback(() => {
    api.touch().catch(e => say(`dokunma: ${(e as Error).message}`, true))
    const r = voice.recorder
    if (!r) return
    if (r.active || r.pending) r.stop(); else r.start()
  }, [api, say, voice.recorder])
  const onAsk = useCallback((text: string) => { api.ask(text, choice).catch(e => say(`soru: ${(e as Error).message}`, true)) }, [api, say, choice])
  const fetchQr = useCallback((u: string, dark: string) => api.qr(u, dark), [api])
  const fetchModels = useCallback((refresh: boolean) => api.models(refresh), [api])

  const listening = !!voice.recorder?.active
  const navBtn = (v: View, label: string) => (
    <button className="nav-btn" aria-current={view === v ? 'page' : undefined} onClick={() => setView(v)}>{label}</button>
  )

  return (
    <div className="shell" data-view={view}>
      <header className="topbar">
        <span className="brand">HEREN</span>
        <nav aria-label="Ana gezinme" className="main-nav">
          {navBtn('home', 'Ana ekran')}{navBtn('services', 'Servisler')}{navBtn('devices', 'Cihazlar')}{navBtn('logs', 'Kayıtlar')}{navBtn('settings', 'Ayarlar')}
        </nav>
        <span className="spacer" />
        <button className={`btn approval-toggle ${state.approvals.length ? 'has-items' : ''}`} aria-expanded={showApprovals}
          aria-controls="approval-inspector" onClick={() => setShowApprovals(s => !s)}>
          Onaylar <span aria-live="polite">{state.approvals.length}</span>
        </button>
      </header>

      <main className={`workspace ${showApprovals ? 'with-inspector' : ''}`}>
        <div className="home" hidden={view !== 'home'}>
          <section className="half half-heren" aria-label="Heren">
            <CharacterPanel state={state.character} onTouch={onTouch} packUrl={packForLook(settings.look)}
              listening={listening} level={voice.recorder?.level ?? 0} wave={voice.recorder?.wave ?? []}
              speaking={voice.speech.speaking} speechWave={voice.speechWave} />
            <VoiceBar voice={state.voice} speaking={voice.speech.speaking} queued={voice.speech.queued}
              recorder={voice.recorder} onStop={voice.stopSpeaking} />
            <Conversation rows={state.conversation} hermes={state.hermes} onAsk={onAsk} />
          </section>
          <section className="half half-control" aria-label="Kumanda">
            {serverId && <div className="server-vitals" aria-label="Sunucu durumu"><Vitals latest={state.metrics[serverId]} history={history} /></div>}
            <ServerControls devices={paired} serverId={serverId} onAction={onAction} />
            <QuickActions devices={devices} onAction={onAction} />
          </section>
        </div>

        {view === 'services' && (serverId
          ? <ServicesView deviceId={serverId} deviceName={names[serverId] ?? serverId} run={runForOutput} />
          : <section className="inspect-view" aria-label="Servisler"><div className="empty">Önce bir sunucu eşle.</div></section>)}

        {view === 'devices' && <section className="inspect-view" aria-label="Cihazlar">
          <div className="section-heading"><div><span className="eyebrow">CİHAZLAR</span><h1>Cihazlar</h1></div><button className="btn" onClick={() => setPairing(true)}>+ Cihaz eşle</button></div>
          {devices.length === 0 && <div className="empty">Henüz cihaz yok. İlk cihazını “Cihaz eşle” ile bağla.</div>}
          <div className="devices">{devices.map(d => (
            <DeviceCard key={d.device_id} device={d} metrics={state.metrics[d.device_id] ?? {}}
              bootEntries={boot[d.device_id]} onAction={onAction} />
          ))}</div>
        </section>}

        {view === 'logs' && <section className="inspect-view" aria-label="Kayıtlar">
          <div className="section-heading"><div><span className="eyebrow">KAYITLAR</span><h1>Kayıtlar</h1></div>
            <div className="btn-row">
              <button className={`btn ${tab === 'activity' ? 'primary' : ''}`} aria-pressed={tab === 'activity'} onClick={() => setTab('activity')}>Etkinlik</button>
              <button className={`btn ${tab === 'audit' ? 'primary' : ''}`} aria-pressed={tab === 'audit'} onClick={() => setTab('audit')}>Denetim</button>
            </div>
          </div>
          {tab === 'activity' ? <Activity rows={state.activity} deviceNames={names} /> : <Audit rows={audit} deviceNames={names} />}
        </section>}

        {view === 'settings' && <SettingsView settings={settings} devices={paired} serverId={serverId} access={state.access} fetchQr={fetchQr} fetchModels={fetchModels} onChange={onSettings} onLogout={onLogout} />}

        {showApprovals && <aside className="approval-inspector" id="approval-inspector" aria-label="Onaylar">
          <div className="section-heading"><h2>İşlem onayları</h2><button className="btn" onClick={() => setShowApprovals(false)}>Kapat</button></div>
          <Approvals approvals={state.approvals} devices={state.devices} onApprove={onApprove} onDeny={onDeny} />
        </aside>}
      </main>

      <footer className="statusbar" role="status">
        <span>{state.connected ? '● Sunucuya bağlı' : '○ Sunucu bağlantısı bekleniyor'}</span>
      </footer>
      {pairing && <PairingModal fetchCode={fetchCode} onClose={() => setPairing(false)} apiBase={api.base} apiKey={apiKey} />}
      {toast && <div role={toast.err ? 'alert' : 'status'} className={`toast ${toast.err ? 'err' : ''}`}>{toast.text}</div>}
    </div>
  )
}

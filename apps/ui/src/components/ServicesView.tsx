import { useCallback, useEffect, useMemo, useState } from 'react'

export interface Service { name: string; state: string; description: string }
export interface Container { name: string; image: string; state: string; status: string }

interface Props {
  deviceId: string
  deviceName: string
  /** Runs an action on the device and resolves with its output (rejects with a readable message). */
  run: (deviceId: string, action: string, params: Record<string, unknown>) => Promise<Record<string, unknown>>
}

const ORDER: Record<string, number> = { failed: 0, running: 1, activating: 2, deactivating: 2, exited: 3, inactive: 4, dead: 4 }
const BORING = new Set(['exited', 'inactive', 'dead'])

export function ServicesView({ deviceId, deviceName, run }: Props) {
  const [services, setServices] = useState<Service[] | null>(null)
  const [failed, setFailed] = useState(0)
  const [containers, setContainers] = useState<{ runtime: string; list: Container[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [all, setAll] = useState(false)
  const [logsFor, setLogsFor] = useState<string | null>(null)
  const [logs, setLogs] = useState<string[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const out = await run(deviceId, 'list_services', {})
      setServices((out.services as Service[]) ?? [])
      setFailed(Number(out.failed ?? 0))
      setError(null)
    } catch (e) { setError((e as Error).message) }
    try {
      const out = await run(deviceId, 'list_containers', {})
      const runtime = String(out.runtime ?? 'none')
      setContainers(runtime === 'none' ? null : { runtime, list: (out.containers as Container[]) ?? [] })
    } catch { setContainers(null) }
  }, [deviceId, run])
  useEffect(() => { void refresh() }, [refresh])

  const act = async (action: string, name: string) => {
    setBusy(name)
    try { await run(deviceId, action, { name }); setError(null) } catch (e) { setError((e as Error).message) }
    finally { setBusy(null); void refresh() }
  }
  const showLogs = async (name: string) => {
    setLogsFor(name); setLogs(null)
    try { const out = await run(deviceId, 'service_logs', { name, lines: 100 }); setLogs((out.lines as string[]) ?? []) }
    catch (e) { setLogs([`kayıt alınamadı: ${(e as Error).message}`]) }
  }

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (services ?? [])
      .filter(s => (all || !BORING.has(s.state) || s.state === 'failed') && (!q || s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)))
      .sort((a, b) => (ORDER[a.state] ?? 9) - (ORDER[b.state] ?? 9) || a.name.localeCompare(b.name))
  }, [services, query, all])

  return (
    <section className="inspect-view services" aria-label="Servisler">
      <div className="section-heading">
        <div><span className="eyebrow">SERVİSLER</span><h1>{deviceName}</h1></div>
        <button className="btn" onClick={() => void refresh()}>Yenile</button>
      </div>
      {error && <div className="err-line">{error}</div>}
      {services && (
        <p className="dim">{failed} hatalı · {services.length} servis</p>
      )}
      <div className="row">
        <input className="input" placeholder="Servis ara" value={query} onChange={e => setQuery(e.target.value)} />
        <label className="check"><input type="checkbox" aria-label="Hepsini göster" checked={all} onChange={e => setAll(e.target.checked)} />Hepsini göster</label>
      </div>
      {services === null && !error && <div className="dim">Servisler okunuyor…</div>}
      {services && (
        <table className="svc-table">
          <thead><tr><th>Servis</th><th>Durum</th><th>Açıklama</th><th></th></tr></thead>
          <tbody>
            {visible.map(s => (
              <tr key={s.name} data-state={s.state} aria-label={s.name}>
                <td className="mono">{s.name}</td>
                <td><span className={`svc-state svc-${s.state}`}>{s.state}</span></td>
                <td className="dim">{s.description}</td>
                <td className="svc-actions">
                  {s.state === 'running'
                    ? <><button className="btn sm" disabled={busy === s.name} onClick={() => void act('restart_service', s.name)}>Yeniden başlat</button>
                        <button className="btn sm" disabled={busy === s.name} onClick={() => void act('stop_service', s.name)}>Durdur</button></>
                    : <button className="btn sm" disabled={busy === s.name} onClick={() => void act('start_service', s.name)}>Başlat</button>}
                  <button className="btn sm" onClick={() => void showLogs(s.name)}>Kayıtlar</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {logsFor && (
        <div className="svc-logs">
          <div className="section-heading"><strong className="mono">{logsFor} · son 100 satır</strong><button className="btn sm" onClick={() => setLogsFor(null)}>Kapat</button></div>
          <pre className="cmd">{logs === null ? 'okunuyor…' : logs.length ? logs.join('\n') : '(boş)'}</pre>
        </div>
      )}
      {containers && (
        <>
          <h2 className="eyebrow" style={{ marginTop: 20 }}>KONTEYNERLER · {containers.runtime}</h2>
          <table className="svc-table">
            <thead><tr><th>Ad</th><th>Durum</th><th>İmaj</th><th></th></tr></thead>
            <tbody>
              {containers.list.map(c => (
                <tr key={c.name} data-state={c.state} aria-label={c.name}>
                  <td className="mono">{c.name}</td>
                  <td><span className={`svc-state svc-${c.state}`}>{c.status}</span></td>
                  <td className="dim mono">{c.image}</td>
                  <td className="svc-actions">
                    {c.state === 'running'
                      ? <><button className="btn sm" onClick={() => void act('restart_container', c.name)}>Yeniden başlat</button>
                          <button className="btn sm" onClick={() => void act('stop_container', c.name)}>Durdur</button></>
                      : <button className="btn sm" onClick={() => void act('start_container', c.name)}>Başlat</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

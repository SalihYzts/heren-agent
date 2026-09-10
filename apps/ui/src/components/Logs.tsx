import type { ActivityRow } from '../lib/store'
import type { AuditRow } from '../lib/types'

const hhmmss = (ts: number) => new Date(ts * 1000).toLocaleTimeString('tr-TR', { hour12: false })

export function Activity({ rows, deviceNames }: { rows: ActivityRow[]; deviceNames: Record<string, string> }) {
  return (
    <div className="panel">
      <div className="panel-h">Etkinlik<span className="count">{rows.length}</span></div>
      {rows.length === 0 && <div className="empty">henüz etkinlik yok</div>}
      <div className="rows">
        {rows.map(r => (
          <div className="row" key={r.request_id}>
            <span className="mute">{hhmmss(r.ts)}</span>
            <span><span className="dev">{deviceNames[r.device_id] ?? r.device_id}</span>{r.action}</span>
            <span><span className={`tag ${r.status}`}>{r.status}</span></span>
            {r.error && <span className="err">{r.error}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export function Audit({ rows, deviceNames }: { rows: AuditRow[]; deviceNames: Record<string, string> }) {
  return (
    <div className="panel">
      <div className="panel-h">Denetim kaydı<span className="count">{rows.length}</span></div>
      {rows.length === 0 && <div className="empty">kayıt yok</div>}
      <div className="rows">
        {rows.map(r => (
          <div className="row" key={r.id} title={JSON.stringify(r.params)}>
            <span className="mute">{hhmmss(r.ts)}</span>
            <span>
              <span className="dev">{deviceNames[r.device_id] ?? r.device_id}</span>{r.action}
              {r.approved_by && <span className="mute"> by {r.approved_by}</span>}
            </span>
            <span><span className={`tag ${r.risk}`}>{r.risk}</span> <span className={`tag ${r.result}`}>{r.result}</span>{r.duration_ms !== null && <span className="mute"> {r.duration_ms}ms</span>}</span>
            {r.error && <span className="err">{r.error}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

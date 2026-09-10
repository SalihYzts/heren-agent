import { useEffect, useState } from 'react'
import type { Approval, Device } from '../lib/types'

interface Props {
  approvals: Approval[]
  devices: Record<string, Pick<Device, 'name'>>
  onApprove: (id: string) => void
  onDeny: (id: string) => void
}

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), intervalMs)
    return () => clearInterval(t)
  }, [intervalMs])
  return now
}

const fmtParams = (p: Record<string, unknown>) =>
  Object.entries(p).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(' ')

export function Approvals({ approvals, devices, onApprove, onDeny }: Props) {
  const now = useNow()
  return (
    <div className="panel">
      <div className="panel-h">Onay bekleyen<span className="count">{approvals.length}</span></div>
      {approvals.length === 0 && <div className="empty">bekleyen onay yok</div>}
      {approvals.map(a => {
        const left = a.expires_at ? Math.max(0, Math.round(a.expires_at - now)) : null
        return (
          <div className="approval" key={a.request_id}>
            <div className="who">
              <span>{a.requested_by}</span> → <span>{devices[a.device_id]?.name ?? a.device_id}</span>
              {' '}<span className={`tag ${a.risk}`}>{a.risk}</span>
            </div>
            <div className="what"><b>{a.action}</b>{Object.keys(a.params).length > 0 && <span className="dim"> {fmtParams(a.params)}</span>}</div>
            <div className="btn-row">
              <button className="btn primary" onClick={() => onApprove(a.request_id)}>Onayla</button>
              <button className="btn" onClick={() => onDeny(a.request_id)}>Reddet</button>
              {left !== null && <span className="ttl" style={{ marginLeft: 'auto', alignSelf: 'center' }}>{left}s</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

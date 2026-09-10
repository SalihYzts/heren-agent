import type { BootEntry, Device, Metrics } from '../lib/types'
import { riskOf } from '../lib/types'

interface Props {
  device: Device
  metrics: Metrics
  bootEntries: BootEntry[] | undefined
  onAction: (deviceId: string, action: string, params: Record<string, unknown>) => void
}

// Buttons shown on the card, in order. Anything else the device declares is
// reachable through the "…" list. Parameterised actions get their own UI.
const QUICK = ['get_status', 'get_boot_entries', 'lock', 'sleep', 'restart', 'shutdown'] as const

function Meter({ label, value, max = 100, unit = '%' }: { label: string; value: number | undefined; max?: number; unit?: string }) {
  const pct = value === undefined ? 0 : Math.min(100, (value / max) * 100)
  return (
    <div className="meter">
      <span className="dim">{label}</span>
      <span className="bar"><i className={pct > 85 ? 'hot' : ''} style={{ width: `${pct}%` }} /></span>
      <span>{value === undefined ? '—' : `${Number.isInteger(value) ? value : value.toFixed(2)}${unit}`}</span>
    </div>
  )
}

export function DeviceCard({ device, metrics, bootEntries, onAction }: Props) {
  const online = device.status === 'online'
  const caps = new Set(device.capabilities)
  const cpu = metrics.cpu_pct ?? (metrics.load1 !== undefined ? metrics.load1 : undefined)
  const cpuIsLoad = metrics.cpu_pct === undefined && metrics.load1 !== undefined
  return (
    <div className="device">
      <div className="device-h">
        <span className={`dot ${device.status}`} />
        <span className="name">{device.name}</span>
        <span className="id">{device.device_id} · {device.platform}</span>
        <span className={`status ${device.status}`}>{device.status}</span>
      </div>
      <div className="meters">
        {cpuIsLoad
          ? <Meter label="LOAD" value={cpu} max={8} unit="" />
          : <Meter label="CPU" value={cpu} />}
        <Meter label="RAM" value={metrics.ram_pct} />
      </div>
      <div className="btn-row">
        {QUICK.filter(a => caps.has(a)).map(a => (
          <button key={a} className={`btn ${riskOf(a) === 'high' ? 'high' : ''}`} disabled={!online}
            onClick={() => onAction(device.device_id, a, {})}>{a.replace(/_/g, ' ')}</button>
        ))}
      </div>
      {bootEntries && bootEntries.length > 0 && (
        <div className="sub">
          <div className="dim mono" style={{ fontSize: 11, marginBottom: 4 }}>NEXT BOOT →</div>
          <div className="btn-row">
            {bootEntries.map(e => (
              <button key={e.id} className="btn high" disabled={!online || !caps.has('set_next_boot')}
                title={e.id} onClick={() => onAction(device.device_id, 'set_next_boot', { entry: e.id })}>
                {e.title}{e.default ? ' *' : ''}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

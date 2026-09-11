// Vitals — the server's numbers, honestly: nothing drawn that was not measured.
import type { Metrics } from '../lib/types'
import { Sparkline } from './Sparkline'

export function fmtBytes(n: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0, v = n
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${i === 0 ? v : v.toFixed(1)} ${units[i]}`
}

export function fmtUptime(s: number): string {
  if (s < 60) return `${Math.floor(s)} sn`
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d} g ${h} sa`
  if (h > 0) return `${h} sa ${m} dk`
  return `${m} dk`
}

export type Level = 'ok' | 'warn' | 'critical'
export const levelOf = (pct: number | undefined, warn = 80, crit = 90): Level =>
  pct === undefined ? 'ok' : pct >= crit ? 'critical' : pct >= warn ? 'warn' : 'ok'

export interface Sample { ts: number; cpu_pct?: number; ram_pct?: number; disk_pct?: number; [k: string]: number | undefined }

interface Props { latest: Metrics | undefined; history: Sample[] }

function Stat({ label, value, sub, level = 'ok', spark }: { label: string; value: string; sub?: string; level?: Level; spark?: number[] }) {
  return (
    <div className="vital" aria-label={label} data-level={level}>
      <div className="vital-h"><span className="vital-label">{label}</span><span className={`vital-value${value.length > 6 ? ' long' : ''}`}>{value}</span></div>
      {sub && <div className="vital-sub">{sub}</div>}
      {spark && spark.length > 1 && <Sparkline values={spark} max={100} label={`${label} son bir saat`} />}
    </div>
  )
}

export function Vitals({ latest, history }: Props) {
  if (!latest) {
    return <div className="vitals-empty dim">Henüz ölçüm yok — sunucu bağlanınca burada canlı sayılar olacak.</div>
  }
  const series = (k: 'cpu_pct' | 'ram_pct' | 'disk_pct') => history.map(h => h[k]).filter((v): v is number => typeof v === 'number')
  const disks = (latest.disks ?? []) as { mount: string; pct: number; used_gb?: number; total_gb?: number }[]
  return (
    <div className="vitals">
      <Stat label="CPU" value={latest.cpu_pct !== undefined ? `${latest.cpu_pct}%` : latest.load1 !== undefined ? `yük ${latest.load1}` : '—'}
        sub={latest.load1 !== undefined ? `yük ${latest.load1}` : undefined} level={levelOf(latest.cpu_pct)} spark={series('cpu_pct')} />
      <Stat label="RAM" value={latest.ram_pct !== undefined ? `${latest.ram_pct}%` : '—'}
        sub={latest.ram_total_mb ? `${(latest.ram_total_mb / 1024).toFixed(1)} GB toplam${latest.swap_pct !== undefined ? ` · takas ${latest.swap_pct}%` : ''}` : undefined}
        level={levelOf(latest.ram_pct)} spark={series('ram_pct')} />
      <Stat label="Disk" value={latest.disk_pct !== undefined ? `${latest.disk_pct}%` : '—'} sub="en dolu bölüm"
        level={levelOf(latest.disk_pct)} spark={series('disk_pct')} />
      {latest.temp_c !== undefined && <Stat label="Sıcaklık" value={`${latest.temp_c}°C`} level={levelOf(latest.temp_c, 80, 90)} />}
      {latest.uptime_s !== undefined && <Stat label="Çalışma süresi" value={fmtUptime(latest.uptime_s)} />}
      {latest.net_rx_bytes !== undefined && <Stat label="Ağ" value={`↓ ${fmtBytes(latest.net_rx_bytes)}`} sub={`↑ ${fmtBytes(latest.net_tx_bytes ?? 0)} · açılıştan beri`} />}
      {disks.length > 0 && (
        <div className="vital vital-wide">
          <div className="vital-label">Bölümler</div>
          {disks.map(d => (
            <div key={d.mount} className="disk-row" aria-label={`Disk ${d.mount}`} data-level={levelOf(d.pct)}>
              <span className="mono">{d.mount}</span>
              <span className="disk-bar"><span style={{ width: `${Math.min(100, d.pct)}%` }} /></span>
              <span className="mono">{d.pct}%{d.total_gb ? ` · ${d.used_gb?.toFixed(0)}/${d.total_gb.toFixed(0)} GB` : ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

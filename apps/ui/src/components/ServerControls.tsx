// Control half — category 1: the server itself + the other paired devices.
// Buttons come from each device's declared capabilities, so nothing is faked:
// a device that can't `lock` shows no lock button.
import type { Device } from '../lib/types'
import { riskOf } from '../lib/types'

export const ACTION_LABEL: Record<string, string> = {
  get_status: 'Durumu göster', get_metrics: 'Kaynakları ölç', get_boot_entries: 'Önyükleme seçenekleri',
  lock: 'Ekranı kilitle', sleep: 'Uyut', restart: 'Yeniden başlat', shutdown: 'Kapat',
  restart_service: 'Servisi yeniden başlat', launch_app: 'Uygulama aç', stop_app: 'Uygulamayı durdur',
  run_approved_command: 'İzinli komut çalıştır', set_next_boot: 'Sonraki açılışı seç', wake: 'Uyandır',
}
// The essentials for a server, in the order an admin reaches for them. Parameterised
// actions (service name, app…) live in "Senin düğmelerin" where the user fills them in.
const SERVER_ORDER = ['get_status', 'get_metrics', 'lock', 'sleep', 'restart', 'shutdown', 'get_boot_entries']
const DEVICE_ORDER = ['get_status', 'lock', 'sleep', 'restart', 'shutdown', 'wake']

interface Props {
  devices: Device[]
  serverId?: string          // which paired device is "the server" (default: first paired)
  onAction: (deviceId: string, action: string, params: Record<string, unknown>) => void
}

function ActionButtons({ device, order, onAction }: { device: Device; order: string[]; onAction: Props['onAction'] }) {
  const online = device.status === 'online'
  const actions = order.filter(a => device.capabilities.includes(a))
  if (actions.length === 0) return <p className="dim">Bu cihaz henüz komut bildirmedi.</p>
  return (
    <div className="ctl-grid">
      {actions.map(a => {
        const high = ['high', 'critical'].includes(riskOf(a))
        return (
          <button key={a} className={`ctl ${high ? 'ctl-high' : ''}`} disabled={!online}
            aria-label={ACTION_LABEL[a] ?? a}
            title={!online ? 'Cihaz çevrimdışı' : high ? 'Çalıştırınca onay ister' : undefined}
            onClick={() => onAction(device.device_id, a, {})}>
            <span className="ctl-label" aria-hidden>{ACTION_LABEL[a] ?? a}</span>
            {high && <span className="ctl-hint" aria-hidden>onay</span>}
          </button>
        )
      })}
    </div>
  )
}

export function ServerControls({ devices, serverId, onAction }: Props) {
  const server = devices.find(d => d.device_id === serverId) ?? devices[0]
  const others = devices.filter(d => d !== server)
  return (
    <>
      <section className="ctl-section" aria-label={server ? `Sunucu · ${server.name}` : 'Sunucu'}>
        <div className="section-heading">
          <div><span className="eyebrow">01 / SUNUCU</span><h2>{server?.name ?? 'Sunucu bağlı değil'}</h2></div>
          {server && <span className={`status-pill ${server.status}`}>{server.status === 'online' ? 'çevrimiçi' : 'çevrimdışı'}</span>}
        </div>
        {server
          ? <ActionButtons device={server} order={SERVER_ORDER} onAction={onAction} />
          : <p className="dim">Cihazlar bölümünden sunucuyu eşle; düğmeler burada belirecek.</p>}
      </section>
      <section className="ctl-section" aria-label={`Diğer cihazlar · ${others.length}`}>
        <div className="section-heading"><div><span className="eyebrow">02 / DİĞER CİHAZLAR</span><h2>Sunucuya bağlı makineler</h2></div></div>
        {others.length === 0 && <p className="dim">Başka cihaz yok. Bir bilgisayar eşlediğinde komutları burada görünür.</p>}
        {others.map(d => (
          <div key={d.device_id} className="ctl-device">
            <div className="ctl-device-h"><span className={`dot ${d.status}`} /><span className="ctl-device-name">{d.name}</span><span className="dim">{d.platform}</span></div>
            <ActionButtons device={d} order={DEVICE_ORDER} onAction={onAction} />
          </div>
        ))}
      </section>
    </>
  )
}

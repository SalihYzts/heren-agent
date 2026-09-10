import { useState } from 'react'
import { riskOf, type Device } from '../lib/types'

type Shortcut = { id: string; name: string; deviceId: string; action: string; value: string }
const STORAGE = 'heren.shortcuts.v1'
const LABELS: Record<string, string> = { get_status: 'Durumu göster', get_metrics: 'Kaynakları ölç', get_boot_entries: 'Önyükleme seçenekleri', lock: 'Ekranı kilitle', sleep: 'Uyut', restart: 'Yeniden başlat', shutdown: 'Kapat', restart_service: 'Servisi yeniden başlat', launch_app: 'Uygulama aç', stop_app: 'Uygulamayı durdur', run_approved_command: 'İzinli komut çalıştır', set_next_boot: 'Sonraki açılışı seç' }
const PARAMS: Record<string, [string, string]> = { restart_service: ['name', 'Servis adı'], launch_app: ['app', 'Uygulama adı'], stop_app: ['app', 'Uygulama adı'], run_approved_command: ['command_id', 'İzinli komut kimliği'], set_next_boot: ['entry', 'Önyükleme kimliği'] }
function restore(): Shortcut[] {
  try {
    const items: unknown = JSON.parse(localStorage.getItem(STORAGE) ?? '[]')
    return Array.isArray(items) ? items.filter((s): s is Shortcut => s && ['id', 'name', 'deviceId', 'action', 'value'].every(k => typeof s[k] === 'string')).slice(0, 30) : []
  } catch { return [] }
}
export function QuickActions({ devices, onAction }: { devices: Device[]; onAction: (deviceId: string, action: string, params: Record<string, unknown>) => void }) {
  const [items, setItems] = useState(restore)
  const [edit, setEdit] = useState<Shortcut | null>(null)
  const [error, setError] = useState('')
  const persist = (next: Shortcut[]) => {
    try { localStorage.setItem(STORAGE, JSON.stringify(next)); setItems(next); setEdit(null); setError('') }
    catch { setError('Düğmeler kaydedilemedi. Tarayıcı depolama iznini kontrol et.') }
  }
  const selected = devices.find(d => d.device_id === edit?.deviceId)
  const param = edit ? PARAMS[edit.action] : undefined
  return <section className="quick-actions ctl-section" aria-label="Senin düğmelerin">
    <div className="section-heading"><div><span className="eyebrow">03 / SENİN DÜĞMELERİN</span><h2>Senin düğmelerin</h2></div>
      <button className="btn" onClick={() => { setError(''); setEdit({ id: crypto.randomUUID(), name: '', deviceId: devices[0]?.device_id ?? '', action: '', value: '' }) }}>Düğme ekle</button></div>
    <p className="section-note">Cihazını ve işlemini seç. Tek dokunuşla çalıştır.</p>
    {items.length === 0 && <div className="shortcuts-empty"><span className="empty-cross">+</span><h2>Burayı kendine göre düzenle.</h2><p>Servislerini, uygulamalarını ve cihaz işlemlerini buraya ekle.</p></div>}
    <div className="shortcut-grid">{items.map(s => {
      const d = devices.find(x => x.device_id === s.deviceId)
      const allowed = d?.status === 'online' && d.capabilities.includes(s.action)
      const high = ['high', 'critical'].includes(riskOf(s.action))
      return <div className="shortcut" key={s.id}>
        <button className="shortcut-run" aria-label={`${s.name} çalıştır`} disabled={!allowed} onClick={() => onAction(s.deviceId, s.action, PARAMS[s.action] ? { [PARAMS[s.action][0]]: s.value } : {})}>
          <span className="shortcut-glyph" aria-hidden>{high ? '!' : '↗'}</span><strong>{s.name}</strong><span>{d?.name ?? 'Cihaz bulunamadı'}</span>
          <small>{!allowed ? 'Çevrimdışı / kullanılamıyor' : LABELS[s.action] ?? s.action}{high ? ' · Onay gerekir' : ''}</small>
        </button>
        <button className="shortcut-edit btn" aria-label={`${s.name} düzenle`} onClick={() => { setError(''); setEdit({ ...s }) }}>Düzenle</button>
      </div>
    })}</div>
    <p className="storage-note">Düzen bu tarayıcıda saklanır. Tehlikeli işlemler ayrıca onay ister.</p>
    {edit && <div className="modal-bg"><section className="modal shortcut-form" role="dialog" aria-modal="true" aria-label="Düğmeyi düzenle">
      <div className="section-heading"><h2>Düğmeyi düzenle</h2><button className="btn" onClick={() => setEdit(null)}>Vazgeç</button></div>
      <form onSubmit={e => { e.preventDefault(); if (!edit.name.trim() || !selected?.capabilities.includes(edit.action) || (param && !edit.value.trim())) { setError('Adı, cihazı ve işlem alanlarını doldur.'); return }; persist([...items.filter(s => s.id !== edit.id), { ...edit, name: edit.name.trim(), value: edit.value.trim() }]) }}>
        <label>Düğme adı<input className="input" maxLength={48} value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} required /></label>
        <label>Cihaz<select className="input" value={edit.deviceId} onChange={e => setEdit({ ...edit, deviceId: e.target.value, action: '', value: '' })} required><option value="">Cihaz seç</option>{devices.map(d => <option key={d.device_id} value={d.device_id}>{d.name}</option>)}</select></label>
        <label>İşlem<select className="input" value={edit.action} onChange={e => setEdit({ ...edit, action: e.target.value, value: '' })} required><option value="">İşlem seç</option>{selected?.capabilities.filter(a => a in LABELS).map(a => <option key={a} value={a}>{LABELS[a]}</option>)}</select></label>
        {param && <label>{param[1]}<input className="input" value={edit.value} onChange={e => setEdit({ ...edit, value: e.target.value })} required /></label>}
        {edit.action && ['high', 'critical'].includes(riskOf(edit.action)) && <p className="danger-note">Bu işlem çalıştırıldığında onay isteyecek.</p>}
        {devices.length === 0 && <p>Önce Cihazlar bölümünden bir cihaz eşle.</p>}
        {error && <p role="alert">{error}</p>}
        <div className="btn-row"><button className="btn primary" type="submit">Kaydet</button>{items.some(s => s.id === edit.id) && <button className="btn high" type="button" onClick={() => persist(items.filter(s => s.id !== edit.id))}>Düğmeyi sil</button>}</div>
      </form>
    </section></div>}
  </section>
}

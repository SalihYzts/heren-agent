import { useEffect, useState } from 'react'
import { LOOKS, THEMES, type Settings } from '../lib/settings'
import { FEATURES } from '../lib/features'
import { ModelPicker } from './ModelPicker'
import type { ModelCatalog } from '../lib/api'
import type { Device } from '../lib/types'

interface Props {
  settings: Settings
  devices: Device[]
  serverId?: string
  access: { urls: string[]; tls: boolean }
  fetchQr?: (url: string) => Promise<Blob>
  fetchModels?: (refresh: boolean) => Promise<ModelCatalog>
  onChange: (s: Settings) => void
  onLogout: () => void
}

export function SettingsView({ settings, devices, serverId, access, fetchQr, fetchModels, onChange, onLogout }: Props) {
  const [guide, setGuide] = useState(false)
  const [qr, setQr] = useState<string | null>(null)
  const first = access.urls[0]
  useEffect(() => {
    if (!first || !fetchQr) { setQr(null); return }
    let url: string | null = null; let on = true
    fetchQr(first).then(b => { if (!on) return; url = URL.createObjectURL(b); setQr(url) }).catch(() => setQr(null))
    return () => { on = false; if (url) URL.revokeObjectURL(url) }
  }, [first, fetchQr])

  return (
    <section className="inspect-view settings" aria-label="Ayarlar">
      <div className="section-heading">
        <div><span className="eyebrow">AYARLAR</span><h1>Ayarlar</h1></div>
        <button className="btn" aria-expanded={guide} onClick={() => setGuide(g => !g)}>Neler yapabilir?</button>
      </div>

      {guide && (
        <section className="guide" aria-label="Özellikler">
          <h2>Heren neler yapabilir?</h2>
          <dl className="guide-list">
            {FEATURES.map(f => <div key={f.title}><dt>{f.title}</dt><dd>{f.body}</dd></div>)}
          </dl>
        </section>
      )}

      <fieldset className="choice-group">
        <legend>Telefondan eriş</legend>
        {access.urls.length === 0 ? (
          <p className="dim">
            Heren şu an sadece bu bilgisayardan açılıyor. Telefon/tabletten girmek için sunucuyu
            <code> HEREN_HOST=0.0.0.0 HEREN_TLS=true </code> ile başlat; adresler burada belirir.
          </p>
        ) : (
          <div className="access">
            <div>
              <p>Aynı Wi‑Fi’deki telefon veya tabletten aç:</p>
              <ul className="access-urls">
                {access.urls.map(u => <li key={u}><a href={u} target="_blank" rel="noreferrer">{u}</a></li>)}
              </ul>
              <p className="dim">{access.tls
                ? 'Kendi imzalı sertifika: ilk açılışta sertifikayı bir kez kabul et; mikrofon için bu şart.'
                : 'https kapalı: sayfa açılır ama mikrofon çalışmaz. HEREN_TLS=true ile başlat.'}</p>
            </div>
            {qr && <img className="access-qr" src={qr} alt={`QR: ${first}`} width={168} height={168} />}
          </div>
        )}
      </fieldset>

      <fieldset className="choice-group">
        <legend>Model</legend>
        <p className="dim">Bu panelin Hermes’te kullanacağı model. Boş = Hermes’in varsayılanı.</p>
        <ModelPicker provider={settings.provider} model={settings.model} fetchCatalog={fetchModels}
          onChange={c => onChange({ ...settings, provider: c.provider, model: c.model })} />
      </fieldset>

      <fieldset className="choice-group">
        <legend>Sunucu</legend>
        <p className="dim">Ana ekrandaki “Sunucu” düğmeleri bu cihaza gider.</p>
        <label className="field">Sunucu cihazı
          <select className="input" value={serverId ?? ''} onChange={e => onChange({ ...settings, server: e.target.value || null })}>
            {devices.length === 0 && <option value="">Henüz cihaz eşlenmedi</option>}
            {devices.map(d => <option key={d.device_id} value={d.device_id}>{d.name} ({d.device_id})</option>)}
          </select>
        </label>
      </fieldset>

      <fieldset className="choice-group">
        <legend>Tema</legend>
        <div className="choice-grid">
          {THEMES.map(t => (
            <label key={t.id} className={`choice ${settings.theme === t.id ? 'is-on' : ''}`}>
              <input type="radio" name="theme" value={t.id} checked={settings.theme === t.id} onChange={() => onChange({ ...settings, theme: t.id })} />
              <span className={`swatch swatch-${t.id}`} aria-hidden />
              <strong>{t.label}</strong><small>{t.hint}</small>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="choice-group">
        <legend>Heren’in görünümü</legend>
        <div className="choice-grid">
          {LOOKS.map(l => (
            <label key={l.id} className={`choice ${settings.look === l.id ? 'is-on' : ''}`}>
              <input type="radio" name="look" value={l.id} checked={settings.look === l.id} onChange={() => onChange({ ...settings, look: l.id })} />
              <span className="swatch swatch-look" aria-hidden>◘</span>
              <strong>{l.label}</strong><small>{l.hint}</small>
            </label>
          ))}
        </div>
        <p className="dim">Yeni görünümler geldikçe burada listelenecek.</p>
      </fieldset>

      <fieldset className="choice-group">
        <legend>Oturum</legend>
        <button className="btn" onClick={onLogout}>Çıkış yap</button>
      </fieldset>
    </section>
  )
}

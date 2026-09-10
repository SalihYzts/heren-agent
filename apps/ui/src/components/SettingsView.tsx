import { LOOKS, THEMES, type Settings } from '../lib/settings'
import type { Device } from '../lib/types'

interface Props { settings: Settings; devices: Device[]; serverId?: string; onChange: (s: Settings) => void; onLogout: () => void }

export function SettingsView({ settings, devices, serverId, onChange, onLogout }: Props) {
  return (
    <section className="inspect-view settings" aria-label="Ayarlar">
      <div className="section-heading"><div><span className="eyebrow">AYARLAR</span><h1>Ayarlar</h1></div></div>

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

import { useCallback, useEffect, useState } from 'react'
import type { ModelCatalog } from '../lib/api'

interface Props {
  provider: string
  model: string
  fetchCatalog?: (refresh: boolean) => Promise<ModelCatalog>
  onChange: (choice: { provider: string; model: string }) => void
}

const CUSTOM = '__custom'

/** Pick the Hermes provider/model for this panel. Catalog from /api/models; free text as fallback. */
export function ModelPicker({ provider, model, fetchCatalog, onChange }: Props) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [custom, setCustom] = useState(false)

  const load = useCallback((refresh: boolean) => {
    if (!fetchCatalog) return
    fetchCatalog(refresh).then(c => { setCatalog(c); setError(null) }).catch(e => { setCatalog(null); setError((e as Error).message) })
  }, [fetchCatalog])
  useEffect(() => { load(false) }, [load])

  const entry = catalog?.providers.find(p => p.id === provider)
  const known = entry?.models ?? []
  const modelIsCustom = custom || (model !== '' && known.length > 0 && !known.includes(model))
  const def = catalog?.default

  if (!catalog) {
    return (
      <div className="two-col">
        {error && <p className="dim">Model listesi alınamadı ({error}); adı elle yaz.</p>}
        <label className="field">Sağlayıcı
          <input className="input" aria-label="Sağlayıcı" placeholder="örn. copilot, openai, anthropic" value={provider}
            onChange={e => onChange({ provider: e.target.value.trim(), model })} />
        </label>
        <label className="field">Model
          <input className="input" aria-label="Model" placeholder="örn. gpt-4.1" value={model}
            onChange={e => onChange({ provider, model: e.target.value.trim() })} />
        </label>
      </div>
    )
  }

  return (
    <div className="model-picker">
      <p className="dim">
        {def?.provider ? `Hermes varsayılanı: ${def.provider} / ${def.model ?? '?'}` : 'Hermes varsayılanı bilinmiyor'}
        {' · '}
        <button type="button" className="linklike" onClick={() => load(true)}>Listeyi yenile</button>
      </p>
      <div className="two-col">
        <label className="field">Sağlayıcı
          <select className="input" aria-label="Sağlayıcı" value={provider}
            onChange={e => { setCustom(false); onChange({ provider: e.target.value, model: '' }) }}>
            <option value="">Hermes varsayılanı</option>
            {catalog.providers.map(p => <option key={p.id} value={p.id}>{p.id}{p.error ? ' (liste yok)' : ''}</option>)}
          </select>
        </label>
        <label className="field">Model
          <select className="input" aria-label="Model" value={modelIsCustom ? CUSTOM : model} disabled={!provider}
            onChange={e => {
              if (e.target.value === CUSTOM) { setCustom(true); return }
              setCustom(false); onChange({ provider, model: e.target.value })
            }}>
            <option value="">{provider ? 'Sağlayıcının varsayılanı' : 'Önce sağlayıcı seç'}</option>
            {known.map(m => <option key={m} value={m}>{m}</option>)}
            <option value={CUSTOM}>Listede yok, elle yaz…</option>
          </select>
        </label>
      </div>
      {modelIsCustom && (
        <label className="field">Model adı
          <input className="input" aria-label="Model adı" placeholder="örn. gpt-7-preview" value={model}
            onChange={e => onChange({ provider, model: e.target.value.trim() })} />
        </label>
      )}
      {entry?.error && <p className="dim">Bu sağlayıcının listesi alınamadı: {entry.error}</p>}
    </div>
  )
}

// User settings: theme + character look. Stored in this browser (localStorage);
// no server round-trip — the panel must feel instant on a phone.

export type ThemeId = 'nothing' | 'paper' | 'ember'
export type LookId = 'heren'

export interface Settings {
  theme: ThemeId
  look: LookId
  server: string | null    // device_id of "the server" on the home screen; null = first paired device
  model: string            // Hermes model for this panel ('' = gateway default)
  provider: string         // Hermes provider slug ('' = gateway default)
}

export const THEMES: Array<{ id: ThemeId; label: string; hint: string }> = [
  { id: 'nothing', label: 'Nothing', hint: 'siyah · gri · kırmızı' },
  { id: 'paper', label: 'Kağıt', hint: 'açık · mürekkep · kırmızı' },
  { id: 'ember', label: 'Kor', hint: 'siyah · turuncu' },
]

/** Character looks: id → ASCII pack url. New art = new entry + a JSON under public/character/. */
export const LOOKS: Array<{ id: LookId; label: string; pack: string; hint: string }> = [
  { id: 'heren', label: 'Heren', pack: '/character/heren.json', hint: 'şapka · gözlük · kollar bağlı' },
]

const STORAGE = 'heren.settings.v1'
const DEFAULTS: Settings = { theme: 'nothing', look: 'heren', server: null, model: '', provider: '' }

export function loadSettings(): Settings {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE) ?? '{}') as Partial<Record<keyof Settings, unknown>>
    const theme = THEMES.some(t => t.id === raw.theme) ? raw.theme as ThemeId : DEFAULTS.theme
    const look = LOOKS.some(l => l.id === raw.look) ? raw.look as LookId : DEFAULTS.look
    const server = typeof raw.server === 'string' && raw.server ? raw.server : null
    const model = typeof raw.model === 'string' ? raw.model.trim() : ''
    const provider = typeof raw.provider === 'string' ? raw.provider.trim() : ''
    return { theme, look, server, model, provider }
  } catch { return { ...DEFAULTS } }
}

export function saveSettings(s: Settings): void {
  try { localStorage.setItem(STORAGE, JSON.stringify(s)) } catch { /* private mode: settings live for the session */ }
}

export function applyTheme(theme: ThemeId): void {
  document.documentElement.dataset.theme = theme
}

export const packForLook = (look: LookId): string => LOOKS.find(l => l.id === look)?.pack ?? LOOKS[0].pack

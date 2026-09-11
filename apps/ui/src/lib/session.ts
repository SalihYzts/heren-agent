// Where the panel's API key lives between visits.
//   remember=false → sessionStorage (dies with the tab)  — shared computer
//   remember=true  → localStorage with a sliding expiry   — your own phone/tablet
// Logout wipes both. The key is never written anywhere else.

const TAB_KEY = 'heren.api_key'
const REMEMBER_KEY = 'heren.session.v1'
export const REMEMBER_MS = 30 * 24 * 3600 * 1000

export function saveSession(key: string, remember: boolean, now = Date.now()): void {
  sessionStorage.setItem(TAB_KEY, key)
  if (remember) {
    try { localStorage.setItem(REMEMBER_KEY, JSON.stringify({ key, exp: now + REMEMBER_MS })) } catch { /* private mode */ }
  } else {
    localStorage.removeItem(REMEMBER_KEY)
  }
}

export function loadSession(now = Date.now()): string | null {
  const tab = sessionStorage.getItem(TAB_KEY)
  if (tab) return tab
  try {
    const raw = localStorage.getItem(REMEMBER_KEY)
    if (!raw) return null
    const { key, exp } = JSON.parse(raw) as { key?: unknown; exp?: unknown }
    if (typeof key !== 'string' || typeof exp !== 'number' || now > exp) { localStorage.removeItem(REMEMBER_KEY); return null }
    localStorage.setItem(REMEMBER_KEY, JSON.stringify({ key, exp: now + REMEMBER_MS }))   // slide
    sessionStorage.setItem(TAB_KEY, key)
    return key
  } catch {
    localStorage.removeItem(REMEMBER_KEY)
    return null
  }
}

export function clearSession(): void {
  sessionStorage.removeItem(TAB_KEY)
  localStorage.removeItem(REMEMBER_KEY)
}

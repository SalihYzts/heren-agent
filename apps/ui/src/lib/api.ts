import type { ActionRecord, ActionResult, AuditRow, CharacterState, Device } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export class Api {
  private key: string
  private base: string
  constructor(key: string, base = '') { this.key = key; this.base = base }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const r = await fetch(this.base + path, {
      method,
      headers: { Authorization: `Bearer ${this.key}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!r.ok) {
      let detail = r.statusText
      try { detail = (await r.json()).detail ?? detail } catch { /* not json */ }
      throw new ApiError(r.status, detail)
    }
    return r.json() as Promise<T>
  }

  devices = () => this.req<Device[]>('GET', '/api/devices')
  pairingCode = () => this.req<{ code: string; ttl_s: number }>('POST', '/api/devices/pairing-code')
  submit = (device_id: string, action: string, params: Record<string, unknown> = {}, requested_by = 'ui') =>
    this.req<ActionResult>('POST', '/api/actions', { device_id, action, params, requested_by })
  actions = (limit = 50) => this.req<ActionRecord[]>('GET', `/api/actions?limit=${limit}`)
  approve = (id: string, approved_by: string) =>
    this.req<ActionResult>('POST', `/api/approvals/${id}/approve`, { approved_by })
  deny = (id: string, denied_by: string) =>
    this.req<ActionResult>('POST', `/api/approvals/${id}/deny`, { denied_by })
  audit = (limit = 100) => this.req<AuditRow[]>('GET', `/api/audit?limit=${limit}`)
  touch = () => this.req<CharacterState>('POST', '/api/character/touch')
  ask = (text: string) => this.req<{ ok: boolean; text: string; error: string | null }>('POST', '/api/ask', { text })

  // ---- voice ----
  voiceStop = () => this.req<{ ok: boolean }>('POST', '/api/voice/stop')
  playback = (state: 'started' | 'finished', clip_id?: string) =>
    this.req<{ ok: boolean }>('POST', '/api/voice/playback', { state, clip_id })
  transcribe = async (wav: ArrayBuffer, ask = false) => {
    const r = await fetch(`${this.base}/api/voice/transcribe?ask=${ask}`, {
      method: 'POST', headers: { Authorization: `Bearer ${this.key}`, 'Content-Type': 'audio/wav' }, body: wav,
    })
    if (!r.ok) throw new ApiError(r.status, r.statusText)
    return r.json() as Promise<{ text: string; asked: boolean; confidence: number | null }>
  }
  /** Authenticated fetch of a synthesized clip (for <audio> playback via blob URL). */
  clip = async (url: string) => {
    const r = await fetch(this.base + url, { headers: { Authorization: `Bearer ${this.key}` } })
    if (!r.ok) throw new ApiError(r.status, r.statusText)
    return r.blob()
  }
}

/** Opens /ws/events and keeps it open; delivers every event (plus a synthetic
 * `__disconnected`) to `onEvent`. Returns a stop function. */
export function connectEvents(key: string, onEvent: (e: { type: string; payload: Record<string, unknown>; ts: number }) => void, base = ''): () => void {
  let ws: WebSocket | null = null
  let stopped = false
  let backoff = 500
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = (base || `${proto}://${location.host}`) + `/ws/events?token=${encodeURIComponent(key)}`

  const open = () => {
    if (stopped) return
    ws = new WebSocket(url)
    ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)) } catch { /* ignore */ } }
    ws.onopen = () => { backoff = 500 }
    ws.onclose = () => {
      onEvent({ type: '__disconnected', payload: {}, ts: Date.now() / 1000 })
      if (!stopped) { setTimeout(open, backoff); backoff = Math.min(backoff * 2, 10000) }
    }
    ws.onerror = () => ws?.close()
  }
  open()
  return () => { stopped = true; ws?.close() }
}

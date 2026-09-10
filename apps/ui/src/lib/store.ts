// Pure reducer over core events. No React, no I/O — fully unit-testable.
import type { Approval, CharacterState, Device, Event, Metrics } from './types'

export interface ActivityRow {
  request_id: string
  device_id: string
  action: string
  status: string
  error?: string | null
  ts: number
}

export interface State {
  connected: boolean
  devices: Record<string, Device>
  metrics: Record<string, Metrics>
  approvals: Approval[]
  activity: ActivityRow[]
  character: CharacterState
}

export const defaultCharacter: CharacterState = {
  schema: 1, activity: 'idle', mood: 'neutral', attention: 'none', energy: 1,
}

export const initialState: State = {
  connected: false, devices: {}, metrics: {}, approvals: [], activity: [], character: defaultCharacter,
}

const ACTIVITY_CAP = 200

function setDevice(s: State, id: string, patch: Partial<Device>): State {
  const prev = s.devices[id]
  return { ...s, devices: { ...s.devices, [id]: { ...(prev ?? blankDevice(id)), ...patch } } }
}

function blankDevice(id: string): Device {
  return { device_id: id, name: id, platform: 'unknown', public_key: '', status: 'offline', last_seen: null, capabilities: [] }
}

export function reduce(s: State, e: Event): State {
  const p = e.payload as Record<string, any>
  switch (e.type) {
    case '__disconnected':
      return { ...s, connected: false }

    case 'ui.snapshot': {
      const devices: Record<string, Device> = {}
      for (const d of (p.devices as Device[]) ?? []) devices[d.device_id] = d
      return {
        ...s, connected: true, devices, approvals: (p.approvals as Approval[]) ?? [],
        character: (p.character as CharacterState) ?? s.character,
      }
    }

    case 'character.state':
      return { ...s, connected: true, character: p as unknown as CharacterState }

    case 'device.paired':
      return setDevice({ ...s, connected: true }, p.device_id, {
        name: p.name ?? p.device_id, status: 'online',
        ...(p.platform ? { platform: p.platform } : {}),
        ...(Array.isArray(p.capabilities) ? { capabilities: p.capabilities } : {}),
      })

    case 'device.online':
      return setDevice({ ...s, connected: true }, p.device_id, {
        status: 'online', last_seen: e.ts,
        ...(p.platform ? { platform: p.platform } : {}),
        ...(p.name ? { name: p.name } : {}),
        ...(Array.isArray(p.capabilities) ? { capabilities: p.capabilities } : {}),
      })

    case 'device.offline':
      return setDevice({ ...s, connected: true }, p.device_id, { status: 'offline' })

    case 'device.metrics': {
      const { device_id, ...rest } = p
      const next = setDevice({ ...s, connected: true }, device_id, { last_seen: e.ts, status: 'online' })
      return { ...next, metrics: { ...s.metrics, [device_id]: { ...rest, ts: e.ts } } }
    }

    case 'ui.approval.needed': {
      if (s.approvals.some(a => a.request_id === p.request_id)) return { ...s, connected: true }
      const a: Approval = {
        request_id: p.request_id, device_id: p.device_id, action: p.action, params: p.params ?? {},
        risk: p.risk, requested_by: p.requested_by, expires_at: p.expires_at,
      }
      return { ...s, connected: true, approvals: [...s.approvals, a] }
    }

    case 'ui.approval.resolved':
      return { ...s, connected: true, approvals: s.approvals.filter(a => a.request_id !== p.request_id) }

    case 'device.action.started':
    case 'device.action.completed':
    case 'device.action.failed':
    case 'device.action.denied':
    case 'device.action.expired': {
      const row: ActivityRow = {
        request_id: p.request_id, device_id: p.device_id, action: p.action,
        status: p.status ?? e.type.split('.').pop()!, error: p.error, ts: e.ts,
      }
      const rest = s.activity.filter(r => r.request_id !== row.request_id)
      const approvals = e.type === 'device.action.expired'
        ? s.approvals.filter(a => a.request_id !== row.request_id) : s.approvals
      return { ...s, connected: true, approvals, activity: [row, ...rest].slice(0, ACTIVITY_CAP) }
    }

    default:
      return s.connected ? s : { ...s, connected: true }
  }
}

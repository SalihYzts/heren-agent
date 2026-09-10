import { describe, expect, it } from 'vitest'
import { initialState, reduce, type State } from './store'

const dev = (id: string, status = 'offline') => ({
  device_id: id, name: id.toUpperCase(), platform: 'linux', public_key: 'ab', status,
  last_seen: null, capabilities: ['get_status', 'shutdown'],
})

const ev = (type: string, payload: Record<string, unknown> = {}) => ({ type, payload, ts: 1 })

describe('store reducer', () => {
  it('snapshot replaces devices and approvals', () => {
    const s = reduce(initialState, ev('ui.snapshot', {
      devices: [dev('a'), dev('b', 'online')],
      approvals: [{ request_id: 'r1', device_id: 'a', action: 'shutdown', params: {}, risk: 'high', requested_by: 'hermes', created_at: 1, status: 'awaiting_approval', approved_by: null }],
    }))
    expect(Object.keys(s.devices)).toEqual(['a', 'b'])
    expect(s.devices.b.status).toBe('online')
    expect(s.approvals.map(a => a.request_id)).toEqual(['r1'])
    expect(s.connected).toBe(true)
  })

  it('device.online / device.offline flip status and keep metrics', () => {
    let s = reduce(initialState, ev('ui.snapshot', { devices: [dev('a')], approvals: [] }))
    s = reduce(s, ev('device.metrics', { device_id: 'a', load1: 0.5, ram_pct: 40 }))
    s = reduce(s, ev('device.online', { device_id: 'a', platform: 'linux' }))
    expect(s.devices.a.status).toBe('online')
    expect(s.metrics.a).toMatchObject({ load1: 0.5, ram_pct: 40 })
    s = reduce(s, ev('device.offline', { device_id: 'a' }))
    expect(s.devices.a.status).toBe('offline')
  })

  it('device.paired adds an unknown device as online with its capabilities', () => {
    const s = reduce(initialState, ev('device.paired', { device_id: 'new', name: 'NEW PC', platform: 'linux', capabilities: ['get_status', 'shutdown'] }))
    expect(s.devices.new).toMatchObject({ name: 'NEW PC', status: 'online', capabilities: ['get_status', 'shutdown'] })
  })

  it('device.online refreshes capabilities when provided', () => {
    let s = reduce(initialState, ev('ui.snapshot', { devices: [dev('a')], approvals: [] }))
    s = reduce(s, ev('device.online', { device_id: 'a', platform: 'linux', capabilities: ['get_status', 'lock', 'restart'] }))
    expect(s.devices.a.capabilities).toEqual(['get_status', 'lock', 'restart'])
  })

  it('approval.needed appends; approval.resolved removes', () => {
    let s = reduce(initialState, ev('ui.approval.needed', {
      request_id: 'r9', device_id: 'a', action: 'restart', params: {}, risk: 'high',
      requested_by: 'hermes', expires_at: 999,
    }))
    expect(s.approvals).toHaveLength(1)
    expect(s.approvals[0].expires_at).toBe(999)
    s = reduce(s, ev('ui.approval.needed', { request_id: 'r9', device_id: 'a', action: 'restart', params: {}, risk: 'high', requested_by: 'hermes' }))
    expect(s.approvals).toHaveLength(1) // idempotent
    s = reduce(s, ev('ui.approval.resolved', { request_id: 'r9', approved: false, by: 'ui' }))
    expect(s.approvals).toHaveLength(0)
  })

  it('action lifecycle events feed the activity log, newest first, capped', () => {
    let s: State = initialState
    for (let i = 0; i < 205; i++) {
      s = reduce(s, ev('device.action.completed', { request_id: `r${i}`, device_id: 'a', action: 'get_status', status: 'completed' }))
    }
    expect(s.activity).toHaveLength(200)
    expect(s.activity[0].request_id).toBe('r204')
  })

  it('unknown event types are ignored without throwing', () => {
    const s = reduce(initialState, ev('hermes.tool.started', { name: 'x' }))
    expect(s).toEqual({ ...initialState, connected: true })
  })

  it('disconnect keeps data but flags connected=false', () => {
    let s = reduce(initialState, ev('ui.snapshot', { devices: [dev('a')], approvals: [] }))
    s = reduce(s, { type: '__disconnected', payload: {}, ts: 0 })
    expect(s.connected).toBe(false)
    expect(s.devices.a).toBeDefined()
  })
})

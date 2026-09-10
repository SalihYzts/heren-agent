import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Event } from './lib/types'
import App from './App'

const api = vi.hoisted(() => ({
  approve: vi.fn().mockResolvedValue({ status: 'completed' }), deny: vi.fn().mockResolvedValue({}),
  audit: vi.fn().mockResolvedValue([]), ask: vi.fn().mockResolvedValue({}), touch: vi.fn().mockResolvedValue({}),
  submit: vi.fn().mockResolvedValue({ status: 'completed', output: {} }),
  listener: null as null | ((e: Event) => void),
}))
const recorder = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), active: false }))
vi.mock('./lib/api', () => ({
  Api: class { approve = api.approve; deny = api.deny; audit = api.audit; ask = api.ask; touch = api.touch; submit = api.submit },
  ApiError: class extends Error {},
  connectEvents: (_key: string, listener: (e: Event) => void) => { api.listener = listener; return () => {} },
}))
vi.mock('./voice/useVoice', () => ({ useVoice: () => ({ speech: { speaking: false, queued: 0 }, recorder, stopSpeaking: vi.fn(), handleEvent: vi.fn() }) }))
vi.mock('./character/loadPack', async importOriginal => {
  const original = await importOriginal<typeof import('./character/loadPack')>()
  return { ...original, loadPack: vi.fn().mockImplementation(async () => ({ pack: (await import('./character/defaultPack')).defaultPack, source: 'builtin' })) }
})

beforeEach(() => { HTMLElement.prototype.scrollIntoView = vi.fn(); localStorage.clear(); sessionStorage.setItem('heren.api_key', 'test-key'); vi.clearAllMocks(); recorder.active = false })
const snapshot = (devices = 1) => act(() => api.listener?.({ type: 'ui.snapshot', ts: 1, payload: {
  devices: Array.from({ length: devices }, (_, i) => ({ device_id: `pc${i}`, name: i === 0 ? 'Sunucu' : `PC ${i}`, status: 'online', platform: 'linux',
    capabilities: ['get_status', 'get_metrics', 'lock', 'restart_service', 'shutdown', 'restart'], public_key: '', last_seen: null })),
  approvals: [{ request_id: 'r1', device_id: 'pc0', action: 'shutdown', params: {}, risk: 'high', requested_by: 'hermes' }],
  character: { schema: 1, activity: 'idle', mood: 'neutral', attention: 'none', energy: 1 },
} }))
const openApp = async (devices = 1) => { await act(async () => { render(<App />) }); snapshot(devices) }

describe('two-half home screen', () => {
  it('splits into a Heren half and a control half, with devices/logs/settings behind navigation', async () => {
    await openApp()
    expect(screen.getByRole('region', { name: 'Heren' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Kumanda' })).toBeVisible()
    for (const v of ['Ana ekran', 'Cihazlar', 'Kayıtlar', 'Ayarlar']) expect(screen.getByRole('button', { name: v })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Denetim' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarlar' }))
    expect(screen.getByRole('heading', { name: 'Ayarlar' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Ana ekran' }))
    expect(screen.getByRole('region', { name: 'Heren' })).toBeVisible()
  })

  it('tapping Heren starts listening and the screen says so', async () => {
    await openApp()
    fireEvent.click(screen.getByTestId('character-stage'))
    expect(recorder.start).toHaveBeenCalledOnce()
    expect(api.touch).toHaveBeenCalledOnce()
    recorder.active = true
    await act(async () => { snapshot() })
    expect(screen.getByTestId('voice-status')).toHaveTextContent('Seni dinliyorum')
  })

  it('control half has server buttons and a separate section for the other paired devices', async () => {
    await openApp(2)
    const control = screen.getByRole('region', { name: 'Kumanda' })
    const server = within(control).getByRole('region', { name: /Sunucu/ })
    expect(within(server).getByRole('button', { name: 'Durumu göster' })).toBeVisible()
    expect(within(server).getByRole('button', { name: 'Yeniden başlat' })).toBeVisible()
    const others = within(control).getByRole('region', { name: /Diğer cihazlar/ })
    expect(within(others).getByText('PC 1')).toBeVisible()
    fireEvent.click(within(server).getByRole('button', { name: 'Durumu göster' }))
    expect(api.submit).toHaveBeenCalledWith('pc0', 'get_status', {})
    expect(within(control).getByRole('region', { name: 'Senin düğmelerin' })).toBeVisible()
  })

  it('shows the approval count everywhere and keeps approve/deny working', async () => {
    await openApp()
    fireEvent.click(screen.getByRole('button', { name: 'Cihazlar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Onaylar 1' }))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Onayla' })) })
    expect(api.approve).toHaveBeenCalledWith('r1', 'ui:dashboard')
    act(() => api.listener?.({ type: 'ui.approval.resolved', payload: { request_id: 'r1' }, ts: 2 }))
    expect(screen.getByRole('button', { name: 'Onaylar 0' })).toBeVisible()
  })

  it('settings switch the theme immediately and persist; character look is selectable', async () => {
    await openApp()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarlar' }))
    fireEvent.click(screen.getByRole('radio', { name: /Kağıt/ }))
    expect(document.documentElement.dataset.theme).toBe('paper')
    expect(JSON.parse(localStorage.getItem('heren.settings.v1')!).theme).toBe('paper')
    expect(screen.getByRole('radio', { name: /^Heren/ })).toBeChecked()
  })

  it('composer sends trimmed text and hides internal tool names', async () => {
    await openApp()
    const input = screen.getByRole('textbox', { name: "Heren'e mesaj" })
    fireEvent.change(input, { target: { value: '  şu tuş çalışmıyor niye  ' } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Gönder' })) })
    expect(api.ask).toHaveBeenCalledWith('şu tuş çalışmıyor niye')
    act(() => api.listener?.({ type: 'hermes.thinking', payload: { input: 'Soru' }, ts: 2 }))
    act(() => api.listener?.({ type: 'hermes.tool.started', payload: { tool: 'internal_tool_identifier' }, ts: 3 }))
    expect(screen.getByTestId('hermes-status')).toHaveTextContent('İşlem yapıyor…')
    expect(screen.queryByText(/internal_tool_identifier/)).not.toBeInTheDocument()
  })
})

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Event } from './lib/types'
import App from './App'

const api = vi.hoisted(() => ({
  approve: vi.fn().mockResolvedValue({ status: 'completed' }), deny: vi.fn().mockResolvedValue({}),
  audit: vi.fn().mockResolvedValue([]), ask: vi.fn().mockResolvedValue({}), touch: vi.fn().mockResolvedValue({}),
  submit: vi.fn().mockResolvedValue({ status: 'completed', output: {} }),
  qr: vi.fn().mockResolvedValue(new Blob(['<svg/>'], { type: 'image/svg+xml' })),
  models: vi.fn().mockResolvedValue({ default: { provider: 'copilot', model: 'gpt-4.1' }, providers: [{ id: 'copilot', models: ['gpt-4.1', 'claude-opus-5'] }, { id: 'anthropic', models: ['claude-sonnet-4-6'] }] }),
  listener: null as null | ((e: Event) => void),
}))
const recorder = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), active: false }))
const speechLevels = vi.hoisted(() => ({ value: [] as number[] }))
const speaking = vi.hoisted(() => ({ value: false }))
vi.mock('./lib/api', () => ({
  Api: class { approve = api.approve; deny = api.deny; audit = api.audit; ask = api.ask; touch = api.touch; submit = api.submit; qr = api.qr; models = api.models },
  ApiError: class extends Error {},
  connectEvents: (_key: string, listener: (e: Event) => void) => { api.listener = listener; return () => {} },
}))
vi.mock('./voice/useVoice', () => ({ useVoice: () => ({ speech: { speaking: speaking.value, queued: 0 }, recorder, stopSpeaking: vi.fn(), handleEvent: vi.fn(), speechWave: speechLevels.value }) }))
vi.mock('./character/loadPack', async importOriginal => {
  const original = await importOriginal<typeof import('./character/loadPack')>()
  return { ...original, loadPack: vi.fn().mockImplementation(async () => ({ pack: (await import('./character/defaultPack')).defaultPack, source: 'builtin' })) }
})

beforeEach(() => { HTMLElement.prototype.scrollIntoView = vi.fn(); URL.createObjectURL = vi.fn(() => 'blob:qr'); URL.revokeObjectURL = vi.fn(); localStorage.clear(); sessionStorage.setItem('heren.api_key', 'test-key'); vi.clearAllMocks(); recorder.active = false; speaking.value = false; speechLevels.value = [] })
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
    expect(api.ask).toHaveBeenCalledWith('şu tuş çalışmıyor niye', { model: '', provider: '' })
    act(() => api.listener?.({ type: 'hermes.thinking', payload: { input: 'Soru' }, ts: 2 }))
    act(() => api.listener?.({ type: 'hermes.tool.started', payload: { tool: 'internal_tool_identifier' }, ts: 3 }))
    expect(screen.getByTestId('hermes-status')).toHaveTextContent('İşlem yapıyor…')
    expect(screen.queryByText(/internal_tool_identifier/)).not.toBeInTheDocument()
  })
})

describe('settings: model, phone access, feature guide', () => {
  it('lets the user pick a Hermes model and sends it with every question', async () => {
    await openApp()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarlar' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Model' }), { target: { value: ' gpt-4.1 ' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Sağlayıcı' }), { target: { value: 'copilot' } })
    expect(JSON.parse(localStorage.getItem('heren.settings.v1')!)).toMatchObject({ model: 'gpt-4.1', provider: 'copilot' })
    fireEvent.click(screen.getByRole('button', { name: 'Ana ekran' }))
    fireEvent.change(screen.getByRole('textbox', { name: "Heren'e mesaj" }), { target: { value: 'selam' } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Gönder' })) })
    expect(api.ask).toHaveBeenCalledWith('selam', { model: 'gpt-4.1', provider: 'copilot' })
  })

  it('shows the phone/tablet urls the core reports, or how to enable them', async () => {
    await openApp()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarlar' }))
    expect(screen.getByText(/HEREN_HOST=0\.0\.0\.0/)).toBeVisible()          // not enabled → tell how
    act(() => api.listener?.({ type: 'ui.snapshot', ts: 3, payload: { devices: [], approvals: [], access: { urls: ['https://192.168.1.5:8700', 'https://box.local:8700'], tls: true } } }))
    expect(screen.getByRole('link', { name: 'https://192.168.1.5:8700' })).toBeVisible()
    expect(screen.getByText(/sertifikayı bir kez kabul/)).toBeVisible()
    expect(await screen.findByRole('img', { name: /QR/ })).toBeInTheDocument()
    expect(api.qr).toHaveBeenCalledWith('https://192.168.1.5:8700', expect.any(String))
  })

  it('has a feature guide that explains what Heren can do', async () => {
    await openApp()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarlar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Neler yapabilir?' }))
    expect(screen.getByRole('heading', { name: 'Heren neler yapabilir?' })).toBeVisible()
    for (const t of ['Konuş', 'Sunucu düğmeleri', 'Onay', 'Telefondan', 'Model']) expect(screen.getAllByText(new RegExp(t)).length).toBeGreaterThan(0)
  })
})

describe('waves on the character', () => {
  it('user wave in front while listening, Heren wave behind while speaking', async () => {
    await openApp()
    const stage = screen.getByTestId('character-stage')
    const waves = () => [...stage.querySelectorAll('svg.wave')].map(s => `${s.getAttribute('data-tone')}:${s.getAttribute('data-active')}`)
    expect(waves()).toEqual(['heren:false', 'user:false'])     // DOM order = paint order: heren behind, user in front
    recorder.active = true; (recorder as { wave?: number[] }).wave = [0.1, 0.7]
    await act(async () => { snapshot() })
    expect(waves()).toEqual(['heren:false', 'user:true'])
    recorder.active = false
    speechLevels.value = [0.3, 0.5]; speaking.value = true
    await act(async () => { snapshot() })
    expect(waves()).toEqual(['heren:true', 'user:false'])
  })
})

describe('settings: model picker from the Hermes catalog', () => {
  it('lists providers/models from /api/models, picks one, and keeps a free-text fallback', async () => {
    await openApp()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarlar' }))
    const provider = await screen.findByRole('combobox', { name: 'Sağlayıcı' }) as HTMLSelectElement
    expect(provider.tagName).toBe('SELECT')
    expect([...provider.options].map(o => o.value)).toEqual(['', 'copilot', 'anthropic'])
    expect(screen.getByText(/Hermes varsayılanı: copilot \/ gpt-4.1/)).toBeInTheDocument()
    fireEvent.change(provider, { target: { value: 'copilot' } })
    const model = screen.getByLabelText('Model') as HTMLSelectElement
    expect([...model.options].map(o => o.value)).toEqual(['', 'gpt-4.1', 'claude-opus-5', '__custom'])
    fireEvent.change(model, { target: { value: 'claude-opus-5' } })
    expect(JSON.parse(localStorage.getItem('heren.settings.v1')!)).toMatchObject({ provider: 'copilot', model: 'claude-opus-5' })
    // free text: for a model the catalog does not know yet
    fireEvent.change(model, { target: { value: '__custom' } })
    const custom = screen.getByLabelText('Model adı')
    fireEvent.change(custom, { target: { value: 'gpt-7-preview' } })
    expect(JSON.parse(localStorage.getItem('heren.settings.v1')!).model).toBe('gpt-7-preview')
    fireEvent.click(screen.getByRole('button', { name: 'Listeyi yenile' }))
    await waitFor(() => expect(api.models).toHaveBeenLastCalledWith(true))
  })

  it('degrades to plain inputs when the catalog is unavailable', async () => {
    api.models.mockRejectedValueOnce(new Error('hermes down'))
    await openApp()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarlar' }))
    const model = await screen.findByLabelText('Model')
    expect(model.tagName).toBe('INPUT')
    expect(screen.getByText(/Model listesi alınamadı/)).toBeInTheDocument()
  })
})

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Api } from '../lib/api'
import { useVoice } from './useVoice'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(r => { resolve = r })
  return { promise, resolve }
}
const trackStop = vi.fn()
const stream = { getTracks: () => [{ stop: trackStop }] } as unknown as MediaStream
const disconnect = vi.fn()
const close = vi.fn().mockResolvedValue(undefined)
let processAudio: ((e: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null
const getUserMedia = vi.fn()
it('shows microphone permission failures instead of pretending to listen', async () => {
  getUserMedia.mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
  const api = apiMock()
  const { result } = renderHook(() => useVoice(api))
  await act(async () => result.current.recorder!.start())
  expect(result.current.recorder?.active).toBe(false)
  expect(result.current.recorder?.error).toContain('Mikrofon izni verilmedi')
})
it('releases the microphone on unmount and measures actual audio input', async () => {
  getUserMedia.mockResolvedValue(stream)
  const api = apiMock()
  const { result, unmount } = renderHook(() => useVoice(api))
  await act(async () => result.current.recorder!.start())
  act(() => processAudio!({ inputBuffer: { getChannelData: () => new Float32Array(4096).fill(.2) } }))
  expect(result.current.recorder?.level).toBeGreaterThan(0)
  unmount()
  expect(trackStop).toHaveBeenCalledOnce()
  expect(close).toHaveBeenCalledOnce()
  expect(api.transcribe).not.toHaveBeenCalled()
})
beforeEach(() => {
  processAudio = null
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  vi.stubGlobal('AudioContext', class {
    sampleRate = 48000
    state = 'running'
    destination = {}
    close = close
    resume = vi.fn().mockResolvedValue(undefined)
    createMediaStreamSource() { return { connect: vi.fn(), disconnect } }
    createScriptProcessor() { return { connect: vi.fn(), disconnect, set onaudioprocess(fn: typeof processAudio) { processAudio = fn } } }
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks() })
function apiMock() {
  const api = new Api('test')
  vi.spyOn(api, 'voiceStop').mockResolvedValue({ ok: true })
  vi.spyOn(api, 'playback').mockResolvedValue({ ok: true })
  vi.spyOn(api, 'transcribe').mockResolvedValue({ text: 'Merhaba', asked: true, confidence: 1 })
  return api
}
it('does not request a mic until clicked, guards duplicate starts and cancels pending permission', async () => {
  const permission = deferred<MediaStream>()
  getUserMedia.mockReturnValue(permission.promise)
  const api = apiMock()
  const { result } = renderHook(() => useVoice(api))
  expect(getUserMedia).not.toHaveBeenCalled()
  act(() => { result.current.recorder!.start(); result.current.recorder!.start() })
  expect(getUserMedia).toHaveBeenCalledTimes(1)
  expect(api.voiceStop).toHaveBeenCalledOnce()
  expect(result.current.recorder?.pending).toBe(true)
  act(() => result.current.recorder!.stop())
  await act(async () => { permission.resolve(stream) })
  expect(trackStop).toHaveBeenCalledOnce()
  expect(result.current.recorder?.active).toBe(false)
  expect(api.transcribe).not.toHaveBeenCalled()
})
it('sends one WAV, locks while transcribing, and surfaces actionable errors', async () => {
  getUserMedia.mockResolvedValue(stream)
  const api = apiMock()
  const response = deferred<{ text: string; asked: boolean; confidence: number | null }>()
  vi.mocked(api.transcribe).mockReturnValue(response.promise)
  const onText = vi.fn()
  const { result } = renderHook(() => useVoice(api, onText))
  await act(async () => result.current.recorder!.start())
  expect(result.current.recorder?.active).toBe(true)
  act(() => processAudio!({ inputBuffer: { getChannelData: () => new Float32Array(24000) } }))
  await act(async () => { result.current.recorder!.stop(); result.current.recorder!.stop() })
  expect(api.transcribe).toHaveBeenCalledOnce()
  expect(api.transcribe).toHaveBeenCalledWith(expect.any(ArrayBuffer), true)
  expect(result.current.recorder?.busy).toBe(true)
  act(() => result.current.recorder!.start())
  expect(getUserMedia).toHaveBeenCalledOnce()
  await act(async () => response.resolve({ text: '', asked: false, confidence: null }))
  expect(result.current.recorder?.busy).toBe(false)
  expect(result.current.recorder?.error).toMatch(/anlaşılamadı.*tekrar/i)
  expect(onText).not.toHaveBeenCalled()
  expect(trackStop).toHaveBeenCalledOnce()
  expect(close).toHaveBeenCalledOnce()
})

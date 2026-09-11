import { describe, expect, it, vi } from 'vitest'
import { openCapture, WORKLET_SOURCE } from './micCapture'

function fakeStream() { return { getTracks: () => [{ stop: vi.fn(), readyState: 'live' }] } as unknown as MediaStream }

describe('openCapture', () => {
  it('prefers AudioWorklet: loads the processor as a blob module and forwards chunks', async () => {
    const posted: Float32Array[] = []
    const port: { onmessage: ((e: { data: Float32Array }) => void) | null } = { onmessage: null }
    const worklet = { addModule: vi.fn().mockResolvedValue(undefined) }
    class FakeWorkletNode { port = port; connect = vi.fn(); disconnect = vi.fn(); constructor(_c: unknown, name: string) { expect(name).toBe('heren-mic') } }
    const ctx = {
      sampleRate: 48000, audioWorklet: worklet, destination: {},
      createMediaStreamSource: () => ({ connect: vi.fn(), disconnect: vi.fn() }),
      createScriptProcessor: vi.fn(),
      close: vi.fn().mockResolvedValue(undefined),
    } as unknown as AudioContext
    vi.stubGlobal('AudioWorkletNode', FakeWorkletNode)
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:worklet'), revokeObjectURL: vi.fn() })
    vi.stubGlobal('Blob', class { parts: unknown; constructor(parts: unknown) { this.parts = parts } })
    const cap = await openCapture(ctx, fakeStream(), c => posted.push(c))
    expect(cap.backend).toBe('worklet')
    expect(worklet.addModule).toHaveBeenCalledWith('blob:worklet')
    expect((ctx as unknown as { createScriptProcessor: ReturnType<typeof vi.fn> }).createScriptProcessor).not.toHaveBeenCalled()
    port.onmessage!({ data: new Float32Array([0.1, 0.2]) })
    expect(posted).toHaveLength(1)
    cap.close()
    expect(port.onmessage).toBeNull()
    vi.unstubAllGlobals()
  })

  it('falls back to ScriptProcessorNode when the worklet is missing or fails to load', async () => {
    const posted: Float32Array[] = []
    let onaudioprocess: ((e: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null = null
    const node = { connect: vi.fn(), disconnect: vi.fn(), set onaudioprocess(f: typeof onaudioprocess) { onaudioprocess = f } }
    const ctx = {
      sampleRate: 48000, destination: {},
      audioWorklet: { addModule: vi.fn().mockRejectedValue(new Error('CSP blocks blob:')) },
      createMediaStreamSource: () => ({ connect: vi.fn(), disconnect: vi.fn() }),
      createScriptProcessor: vi.fn(() => node),
    } as unknown as AudioContext
    vi.stubGlobal('AudioWorkletNode', class {})
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() })
    vi.stubGlobal('Blob', class { parts: unknown; constructor(parts: unknown) { this.parts = parts } })
    const cap = await openCapture(ctx, fakeStream(), c => posted.push(c))
    expect(cap.backend).toBe('script-processor')
    onaudioprocess!({ inputBuffer: { getChannelData: () => new Float32Array(4) } })
    expect(posted).toHaveLength(1)
    cap.close()
    expect(onaudioprocess).toBeNull()
    vi.unstubAllGlobals()
  })

  it('the worklet source registers a processor that batches ~4096 samples', () => {
    expect(WORKLET_SOURCE).toContain("registerProcessor('heren-mic'")
    expect(WORKLET_SOURCE).toContain('4096')
  })
})

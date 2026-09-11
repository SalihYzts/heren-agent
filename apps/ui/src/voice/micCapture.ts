// micCapture — one interface, two backends. AudioWorklet runs off the main thread (no glitches
// when the UI is busy); ScriptProcessorNode is the deprecated-but-everywhere fallback.
// Both hand the caller mono Float32 chunks of ~4096 samples at the context's sample rate.

export interface Capture { backend: 'worklet' | 'script-processor'; close: () => void }

const CHUNK = 4096

// Inlined so the build needs no extra file; loaded as a blob: module.
export const WORKLET_SOURCE = `
class HerenMic extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(${CHUNK}); this.n = 0 }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (!ch) return true
    for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i]
      if (this.n === this.buf.length) { this.port.postMessage(this.buf); this.buf = new Float32Array(${CHUNK}); this.n = 0 }
    }
    return true
  }
}
registerProcessor('heren-mic', HerenMic)
`

export async function openCapture(ctx: AudioContext, stream: MediaStream, onChunk: (chunk: Float32Array) => void): Promise<Capture> {
  const src = ctx.createMediaStreamSource(stream)
  if (ctx.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
    try {
      const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }))
      try { await ctx.audioWorklet.addModule(url) } finally { URL.revokeObjectURL(url) }
      const node = new AudioWorkletNode(ctx, 'heren-mic', { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1 })
      node.port.onmessage = (e: MessageEvent<Float32Array>) => onChunk(e.data)
      src.connect(node)
      return {
        backend: 'worklet',
        close: () => { node.port.onmessage = null; node.disconnect(); src.disconnect() },
      }
    } catch {
      // CSP without blob:, old Safari, etc. → fall through
    }
  }
  const node = ctx.createScriptProcessor(CHUNK, 1, 1)
  node.onaudioprocess = ev => onChunk(new Float32Array(ev.inputBuffer.getChannelData(0)))
  src.connect(node); node.connect(ctx.destination)   // SPN only fires when connected to the graph
  return {
    backend: 'script-processor',
    close: () => { node.onaudioprocess = null; node.disconnect(); src.disconnect() },
  }
}

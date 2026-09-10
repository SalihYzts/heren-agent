import { describe, expect, it } from 'vitest'
import { encodeWav } from './wav'

const u32 = (b: Uint8Array, o: number) => b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)
const u16 = (b: Uint8Array, o: number) => b[o] | (b[o + 1] << 8)
const ascii = (b: Uint8Array, o: number, n: number) => String.fromCharCode(...b.slice(o, o + n))

describe('encodeWav', () => {
  it('writes a valid 16-bit mono PCM RIFF header', () => {
    const wav = new Uint8Array(encodeWav([new Float32Array([0, 0.5, -0.5, 1, -1])], 16000))
    expect(ascii(wav, 0, 4)).toBe('RIFF')
    expect(ascii(wav, 8, 4)).toBe('WAVE')
    expect(u16(wav, 22)).toBe(1)          // channels
    expect(u32(wav, 24)).toBe(16000)      // sample rate
    expect(u16(wav, 34)).toBe(16)         // bits
    expect(u32(wav, 40)).toBe(10)         // data bytes = 5 samples * 2
    expect(wav.length).toBe(44 + 10)
    expect(u32(wav, 4)).toBe(wav.length - 8)
  })

  it('clamps and scales samples, concatenating chunks', () => {
    const wav = new Uint8Array(encodeWav([new Float32Array([1.5]), new Float32Array([-2, 0.25])], 8000))
    const s = new Int16Array(wav.buffer.slice(44))
    expect(Array.from(s)).toEqual([32767, -32768, Math.round(0.25 * 32767)])
  })

  it('downsamples to the target rate when the source is faster', () => {
    const src = new Float32Array(48000).fill(0.1)   // 1 s @ 48 kHz
    const wav = new Uint8Array(encodeWav([src], 16000, 48000))
    expect(u32(wav, 24)).toBe(16000)
    expect(u32(wav, 40)).toBe(16000 * 2)
  })
})

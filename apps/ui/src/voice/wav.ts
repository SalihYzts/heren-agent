// Float32 PCM chunks → 16-bit mono WAV (ArrayBuffer). Optional naive decimation
// when the capture rate is higher than the target (mic 48 kHz → 16 kHz for STT).
export function encodeWav(chunks: Float32Array[], sampleRate: number, sourceRate = sampleRate): ArrayBuffer {
  let total = 0
  for (const c of chunks) total += c.length
  let pcm = new Float32Array(total)
  let off = 0
  for (const c of chunks) { pcm.set(c, off); off += c.length }

  if (sourceRate > sampleRate) {
    const ratio = sourceRate / sampleRate
    const n = Math.floor(pcm.length / ratio)
    const out = new Float32Array(n)
    for (let i = 0; i < n; i++) {
      // average the source window → cheap anti-aliasing
      const a = Math.floor(i * ratio), b = Math.floor((i + 1) * ratio)
      let s = 0
      for (let j = a; j < b; j++) s += pcm[j]
      out[i] = s / Math.max(1, b - a)
    }
    pcm = out
  }

  const buf = new ArrayBuffer(44 + pcm.length * 2)
  const v = new DataView(buf)
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); v.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE')
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  str(36, 'data'); v.setUint32(40, pcm.length * 2, true)
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]))
    v.setInt16(44 + i * 2, s < 0 ? Math.round(s * 32768) : Math.round(s * 32767), true)
  }
  return buf
}

// useVoice — wires SpeechQueue (playback) and a click-to-record Recorder (capture) into React.
// Playback needs the bearer, so clips are fetched via Api and played from blobs.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Api } from '../lib/api'
import type { Event } from '../lib/types'
import type { Recorder } from '../components/VoiceBar'
import { SpeechQueue, audioPlayer, type SpeechState } from './speechQueue'
import { encodeWav } from './wav'
import { SilenceDetector } from './silence'
import { openCapture, type Capture } from './micCapture'

const STT_RATE = 16000
const WAVE_LEN = 48                       // samples kept for the waveform ring
// speak → quiet for 1.5 s → auto-send; nothing said for 15 s → stop quietly
const SILENCE = { threshold: 0.06, holdMs: 1500, minSpeechMs: 300, maxMs: 15000 }

/** Turkish, actionable message for a getUserMedia failure. */
export function micErrorMessage(e: unknown): string {
  const name = (e as { name?: string })?.name ?? ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Mikrofon izni verilmedi. Tarayıcı adres çubuğundan mikrofon iznini aç ve tekrar dene.'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'Mikrofon bulunamadı. Bir mikrofon bağlı mı kontrol et.'
  if (name === 'NotReadableError') return 'Mikrofon başka bir uygulama tarafından kullanılıyor.'
  return `Mikrofon açılamadı: ${(e as Error)?.message ?? 'bilinmeyen hata'}`
}

interface Media { ctx: AudioContext; stream: MediaStream; capture: Capture; chunks: Float32Array[]; silence: SilenceDetector }

export function useVoice(api: Api, onTranscribed?: (text: string) => void, choice?: { model?: string; provider?: string }) {
  const [speech, setSpeech] = useState<SpeechState>({ speaking: false, queued: 0 })
  const [speechWave, setSpeechWave] = useState<number[]>([])
  const queue = useMemo(() => new SpeechQueue(audioPlayer(url => api.clip(url), lvl =>
    setSpeechWave(w => lvl === 0 && w.length === 0 ? w : lvl === 0 ? [] : [...w.slice(-(WAVE_LEN - 1)), lvl]))), [api])
  useEffect(() => {
    let was = false
    return queue.onChange(s => {
      setSpeech(s)
      if (s.speaking !== was) {  // tell core so the character keeps 'speaking' until audio really ends
        was = s.speaking
        void api.playback(s.speaking ? 'started' : 'finished').catch(() => {})
      }
    })
  }, [queue, api])
  const handleEvent = useCallback((e: Event) => queue.handle(e), [queue])

  // ---- recorder (click to start, click to send) ---------------------------
  const [active, setActive] = useState(false)
  const [pending, setPending] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [level, setLevel] = useState(0)
  const [wave, setWave] = useState<number[]>([])
  const stopRef = useRef<() => void>(() => {})
  const starting = useRef(false)
  const generation = useRef(0)
  const media = useRef<Media | null>(null)
  const hasMic = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== 'undefined'

  const release = useCallback((m: Media | null) => {
    if (!m) return
    m.capture.close(); m.stream.getTracks().forEach(t => t.stop())
    void m.ctx.close().catch(() => {})
  }, [])

  const start = useCallback(async () => {
    if (media.current || starting.current || busy) return
    starting.current = true
    setPending(true); setError(undefined)
    const token = ++generation.current
    queue.handle({ type: 'voice.interrupt', payload: {}, ts: Date.now() / 1000 })  // barge-in: stop Heren talking
    void api.voiceStop().catch(() => {})
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
      if (token !== generation.current) { stream.getTracks().forEach(t => t.stop()); return }  // cancelled meanwhile
      const ctx = new AudioContext()
      const chunks: Float32Array[] = []
      const silence = new SilenceDetector(SILENCE)
      const capture = await openCapture(ctx, stream, buf => {
        chunks.push(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i += 16) sum += buf[i] * buf[i]
        const lvl = Math.min(1, Math.sqrt(sum / (buf.length / 16)) * 4)   // RMS → 0..1 feedback
        setLevel(lvl)
        setWave(w => [...w.slice(-(WAVE_LEN - 1)), lvl])
        const verdict = silence.feed(lvl, performance.now())
        if (verdict === 'send') stopRef.current()
        else if (verdict === 'timeout') { setError('Ses duyamadım. Heren’e dokunup tekrar dene.'); stopRef.current() }
      })
      if (token !== generation.current) { capture.close(); stream.getTracks().forEach(t => t.stop()); void ctx.close().catch(() => {}); return }
      media.current = { ctx, stream, capture, chunks, silence }
      setActive(true)
    } catch (e) {
      setError(micErrorMessage(e))
    } finally {
      if (token === generation.current) { starting.current = false; setPending(false) }
    }
  }, [api, queue, busy])

  const stop = useCallback(async () => {
    ++generation.current
    starting.current = false
    setPending(false)
    const m = media.current
    if (!m) return
    media.current = null
    setActive(false); setLevel(0); setWave([])
    const rate = m.ctx.sampleRate
    release(m)
    const wav = encodeWav(m.chunks, STT_RATE, rate)
    if (wav.byteLength <= 44 + STT_RATE * 2 * 0.3) { setError('Çok kısa kayıt. Konuşmaya başla, bitince tekrar dokun.'); return }
    setBusy(true)
    try {
      const r = await api.transcribe(wav, true, choice)
      if (!r.text.trim()) { setError('Söylediğin anlaşılamadı. Biraz daha yakından ve net konuşup tekrar dene.'); return }
      onTranscribed?.(r.text)
      if (r.asked && r.ask && !r.ask.ok) setError(`Heren cevap veremedi: ${r.ask.error ?? 'bilinmeyen hata'}`)
    } catch (e) {
      setError(`Ses gönderilemedi: ${(e as Error).message}. Sunucu bağlantısını kontrol et.`)
    } finally { setBusy(false) }
  }, [api, onTranscribed, release, choice])

  stopRef.current = () => { void stop() }

  // unmount: never leave the mic open
  useEffect(() => () => { ++generation.current; const m = media.current; media.current = null; release(m) }, [release])

  const recorder: Recorder | null = hasMic
    ? { start: () => { void start() }, stop: () => { void stop() }, active, pending, busy, error, level, wave }
    : null
  const stopSpeaking = useCallback(() => { queue.handle({ type: 'voice.interrupt', payload: {}, ts: Date.now() / 1000 }); void api.voiceStop().catch(() => {}) }, [api, queue])

  return { speech, handleEvent, recorder, stopSpeaking, speechWave }
}

// useVoice — wires SpeechQueue (playback) and a push-to-talk Recorder (capture) into React.
// Playback needs the bearer, so clips are fetched via Api and played from blobs.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Api } from '../lib/api'
import type { Event } from '../lib/types'
import type { Recorder } from '../components/VoiceBar'
import { SpeechQueue, audioPlayer, type SpeechState } from './speechQueue'
import { encodeWav } from './wav'

const STT_RATE = 16000

export function useVoice(api: Api, onTranscribed?: (text: string) => void) {
  const [speech, setSpeech] = useState<SpeechState>({ speaking: false, queued: 0 })
  const queue = useMemo(() => new SpeechQueue(audioPlayer(url => api.clip(url))), [api])
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

  // ---- recorder (push-to-talk) ------------------------------------------
  const [active, setActive] = useState(false)
  const media = useRef<{ ctx: AudioContext; stream: MediaStream; node: ScriptProcessorNode; chunks: Float32Array[] } | null>(null)
  const hasMic = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== 'undefined'

  const start = useCallback(async () => {
    if (media.current) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
      const ctx = new AudioContext()
      const src = ctx.createMediaStreamSource(stream)
      const node = ctx.createScriptProcessor(4096, 1, 1)
      const chunks: Float32Array[] = []
      node.onaudioprocess = ev => chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)))
      src.connect(node); node.connect(ctx.destination)
      media.current = { ctx, stream, node, chunks }
      setActive(true)
      queue.handle({ type: 'voice.interrupt', payload: {}, ts: Date.now() / 1000 })  // barge-in locally
      void api.voiceStop().catch(() => {})
    } catch { /* permission denied → stays inactive */ }
  }, [api, queue])

  const stop = useCallback(async () => {
    const m = media.current
    if (!m) return
    media.current = null
    setActive(false)
    m.node.disconnect(); m.stream.getTracks().forEach(t => t.stop())
    const rate = m.ctx.sampleRate
    await m.ctx.close()
    const wav = encodeWav(m.chunks, STT_RATE, rate)
    if (wav.byteLength <= 44 + STT_RATE * 2 * 0.3) return  // < 0.3 s: a tap, not speech
    try {
      const r = await api.transcribe(wav, true)
      if (r.text) onTranscribed?.(r.text)
    } catch { /* surfaced via voice.error / toast by caller */ }
  }, [api, onTranscribed])

  const recorder: Recorder | null = hasMic ? { start: () => { void start() }, stop: () => { void stop() }, active } : null
  const stopSpeaking = useCallback(() => { queue.handle({ type: 'voice.interrupt', payload: {}, ts: Date.now() / 1000 }); void api.voiceStop().catch(() => {}) }, [api, queue])

  return { speech, handleEvent, recorder, stopSpeaking }
}

import type { VoiceStatus } from '../lib/store'

export interface Recorder {
  start(): void
  stop(): void
  active: boolean
}

interface Props {
  voice: VoiceStatus
  speaking: boolean
  queued: number
  recorder: Recorder | null   // null = no microphone available in this browser/context
  onStop: () => void
}

export function VoiceBar({ voice, speaking, queued, recorder, onStop }: Props) {
  const status = speaking ? `konuşuyor${queued > 0 ? ` · +${queued}` : ''}` : recorder?.active ? 'dinliyor…' : 'sessiz'
  return (
    <div className="voicebar" data-testid="voicebar">
      <span className="mono dim">ses</span>
      <span className="mono" data-testid="voice-status" data-speaking={speaking ? '1' : '0'}>{status}</span>
      {speaking && <button className="btn danger" type="button" onClick={onStop}>Durdur</button>}
      {voice.stt !== 'none' && (
        <button className={`btn ${recorder?.active ? 'primary' : ''}`} type="button"
          disabled={!recorder} title={recorder ? 'basılı tut, konuş, bırak' : 'mikrofon yok (https ya da izin gerekli)'}
          onPointerDown={() => recorder?.start()} onPointerUp={() => recorder?.stop()} onPointerLeave={() => recorder?.active && recorder.stop()}>
          ● Konuş
        </button>
      )}
      {voice.transcript && <span className="dim" data-testid="voice-transcript">“{voice.transcript}”</span>}
      {voice.error && <span className="err mono">{voice.error}</span>}
      <span className="spacer" />
      <span className="mono dim" style={{ fontSize: 10 }}>tts {voice.tts} · stt {voice.stt}</span>
    </div>
  )
}

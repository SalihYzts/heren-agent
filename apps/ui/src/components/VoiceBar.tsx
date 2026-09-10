import type { VoiceStatus } from '../lib/store'

export interface Recorder {
  start(): void
  stop(): void
  active: boolean
  pending?: boolean
  busy?: boolean
  error?: string
  level?: number
}

interface Props {
  voice: VoiceStatus
  speaking: boolean
  queued: number
  recorder: Recorder | null   // null = no microphone available in this browser/context
  onStop: () => void
}

export function VoiceBar({ voice, speaking, queued, recorder, onStop }: Props) {
  const status = recorder?.active ? 'Seni dinliyorum' : recorder?.pending ? 'Mikrofon izni bekleniyor…' : recorder?.busy ? 'Sesin işleniyor…' : speaking ? `konuşuyor${queued > 0 ? ` · +${queued}` : ''}` : 'Heren’e dokun, konuşalım'
  return (
    <div className="voicebar" data-testid="voicebar">
      <span role="status" aria-live="polite" className="listening-status" data-testid="voice-status" data-speaking={speaking ? '1' : '0'} data-listening={recorder?.active ? 'true' : 'false'}>{status}</span>
      {recorder?.active && <meter aria-label="Mikrofon ses seviyesi" min={0} max={1} value={recorder.level ?? 0} />}
      {speaking && <button className="btn danger" type="button" onClick={onStop}>Durdur</button>}
      {voice.stt !== 'none' && (
        <button className={`btn voice-record ${recorder?.active ? 'primary' : ''}`} type="button"
          aria-pressed={recorder?.active ?? false}
          disabled={!recorder || recorder.busy} title={recorder ? 'Konuşmak için tıkla; bitince tekrar tıkla ve gönder.' : 'Mikrofon kullanılamıyor. HTTPS veya localhost üzerinden açın ve mikrofon iznini kontrol edin.'}
          onClick={() => recorder?.active || recorder?.pending ? recorder.stop() : recorder?.start()}>
          {recorder?.pending ? 'İptal et' : recorder?.active ? 'Bitir ve gönder' : 'Konuşmaya başla'}
        </button>
      )}
      {voice.transcript && <span className="dim" data-testid="voice-transcript">“{voice.transcript}”</span>}
      {(recorder?.error || voice.error) && <span role="alert" className="err">{recorder?.error || voice.error}</span>}
      {!recorder && <span className="dim">Mikrofon için HTTPS / localhost ve tarayıcı izni gerekli.</span>}
      {voice.stt === 'none' && <span role="status">Ses tanıma motoru bağlı değil.</span>}
      <details className="voice-details"><summary>Ses bilgisi</summary>tts {voice.tts} · stt {voice.stt}</details>
    </div>
  )
}

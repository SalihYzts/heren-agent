import { useEffect, useState } from 'react'
import type { CharacterState } from '../lib/types'
import { AsciiCharacterRenderer } from '../character/AsciiCharacterRenderer'
import { defaultPack } from '../character/defaultPack'
import { loadPack, type LoadedPack } from '../character/loadPack'
import { Waveform } from './Waveform'

interface Props {
  state: CharacterState
  onTouch: () => void
  packUrl?: string
  listening?: boolean       // mic is open (recorder active) — drawn on the stage as feedback
  level?: number            // 0..1 mic level while listening
  wave?: number[]           // recent mic levels → green wave in front of Heren
  speaking?: boolean        // Heren's clip is playing
  speechWave?: number[]     // Heren's playback levels → wave behind Heren, theme colour
}

export const PACK_URL = '/character/heren.json'

const ACTIVITY_TR: Record<CharacterState['activity'], string> = {
  idle: 'hazır', listening: 'dinliyor', thinking: 'düşünüyor', speaking: 'konuşuyor',
  working: 'işlem yapıyor', sleeping: 'uyuyor', waking: 'uyanıyor',
}
const MOOD_TR: Record<CharacterState['mood'], string> = {
  neutral: '', happy: 'keyfi yerinde', sleepy: 'uykulu', annoyed: 'sinirli', confused: 'kafası karışık',
}

export function CharacterPanel({ state, onTouch, packUrl = PACK_URL, listening = false, level = 0, wave = [], speaking = false, speechWave = [] }: Props) {
  const [loaded, setLoaded] = useState<LoadedPack>({ pack: defaultPack, source: 'builtin' })
  useEffect(() => { let on = true; loadPack(packUrl).then(p => { if (on) setLoaded(p) }); return () => { on = false } }, [packUrl])
  const sleeping = state.activity === 'sleeping'
  const aspect = (loaded.pack.cell.cols * 0.6) / loaded.pack.cell.rows
  const caption = listening ? 'Seni dinliyorum' : [ACTIVITY_TR[state.activity], MOOD_TR[state.mood]].filter(Boolean).join(' · ')

  return (
    <div className="character" data-testid="character-panel" data-pack={loaded.source}>
      <button type="button" className={`character-b ${sleeping ? 'is-sleeping' : ''} ${listening ? 'is-listening' : ''}`}
        onClick={onTouch} aria-label={listening ? 'Dinlemeyi bitir ve gönder' : sleeping ? 'Heren’i uyandır' : 'Heren’e dokun, konuş'}>
        <div className="character-stage" style={{ aspectRatio: `${aspect}` }} data-testid="character-stage">
          <Waveform levels={speechWave} active={speaking && !listening} tone="heren" className="wave-behind" />
          <AsciiCharacterRenderer pack={loaded.pack} activity={listening ? 'listening' : state.activity} mood={state.mood} energy={state.energy} className="character-art" />
          {sleeping && !listening && <div className="zzz mono" aria-hidden>z<span>z</span><span>z</span></div>}
          {listening && <div className="listen-ring" aria-hidden style={{ opacity: 0.35 + level * 0.65 }} />}
          <Waveform levels={wave} active={listening} tone="user" className="wave-front" />
        </div>
        <div className="character-caption" aria-live="polite">
          <span className={`caption-dot ${listening ? 'live' : ''}`} aria-hidden />
          <span data-testid="character-caption">{caption}</span>
          {!listening && !sleeping && <span className="dim"> — dokun, konuş</span>}
        </div>
      </button>
      <details className="character-details">
        <summary>Heren’in durumu</summary>
        <dl className="kv">
          <dt>Dikkat</dt><dd>{state.attention === 'none' ? 'serbest' : state.attention === 'user' ? 'sende' : state.attention === 'device' ? 'cihazda' : 'bildirimde'}</dd>
          <dt>Enerji</dt><dd>{Math.round(state.energy * 100)}%</dd>
          {loaded.error && <><dt>Görsel</dt><dd className="warn" data-testid="pack-warning">{loaded.error} → yerleşik</dd></>}
        </dl>
      </details>
    </div>
  )
}

import type { CharacterState } from '../lib/types'
import { AsciiCharacterRenderer } from '../character/AsciiCharacterRenderer'
import { defaultPack } from '../character/defaultPack'

interface Props {
  state: CharacterState
  onTouch: () => void
}

export function CharacterPanel({ state, onTouch }: Props) {
  return (
    <div className="panel character" data-testid="character-panel">
      <div className="panel-h">Heren<span className="count">{state.activity} · {state.mood}</span></div>
      <div className="character-b" onClick={onTouch} title="dokun → dinle / uyandır">
        <AsciiCharacterRenderer pack={defaultPack} activity={state.activity} mood={state.mood} className="character-art" />
        <div className="character-meta mono">
          <div><span className="dim">ATTN</span> {state.attention}</div>
          <div className="meter">
            <span className="dim">ENERGY</span>
            <span className="bar"><i className={state.energy < 0.35 ? 'hot' : ''} style={{ width: `${Math.round(state.energy * 100)}%` }} /></span>
            <span>{Math.round(state.energy * 100)}%</span>
          </div>
        </div>
      </div>
    </div>
  )
}

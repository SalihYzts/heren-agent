import { useEffect, useRef, useState } from 'react'
import type { ConversationRow, HermesStatus } from '../lib/store'

interface Props {
  rows: ConversationRow[]
  hermes: HermesStatus
  onAsk: (text: string) => void
}

const hhmm = (ts: number) => new Date(ts * 1000).toLocaleTimeString('tr-TR', { hour12: false, hour: '2-digit', minute: '2-digit' })

export function Conversation({ rows, hermes, onAsk }: Props) {
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [rows.length, rows.at(-1)?.text])

  const submit = () => {
    const t = text.trim()
    if (!t || hermes.busy) return
    onAsk(t)
    setText('')
  }

  const status = hermes.reachable === false ? 'hermes erişilemez'
    : hermes.busy ? (hermes.tool ? `çalışıyor: ${hermes.tool}` : 'düşünüyor…')
    : hermes.reachable ? 'hermes hazır' : 'hermes ?'

  return (
    <div className="panel conversation" data-testid="conversation">
      <div className="panel-h">Konuşma<span className="count" data-testid="hermes-status">{status}</span></div>
      <div className="conv-rows">
        {rows.length === 0 && <div className="empty">Heren'e bir şey sor</div>}
        {rows.map(r => (
          <div className={`conv-row ${r.role}`} key={r.id}>
            <span className="mute mono">{hhmm(r.ts)}</span>
            <span className="who mono">{r.role === 'user' ? 'sen' : r.role === 'heren' ? 'heren' : 'hata'}</span>
            <span className="text">{r.text}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form className="conv-input" onSubmit={e => { e.preventDefault(); submit() }}>
        <input className="input" value={text} onChange={e => setText(e.target.value)}
          placeholder={hermes.busy ? 'bekle…' : 'sunucu nasıl? / PC\'yi kilitle'} disabled={hermes.busy} />
        <button className="btn primary" type="submit" disabled={hermes.busy || !text.trim()}>Sor</button>
      </form>
    </div>
  )
}

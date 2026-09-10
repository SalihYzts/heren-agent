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

  // Never leak tool identifiers to the screen; the user cares that Heren is doing something, not which tool.
  const status = hermes.reachable === false ? 'Heren’in beyni erişilemez'
    : hermes.busy ? (hermes.tool ? 'İşlem yapıyor…' : 'Düşünüyor…')
    : hermes.reachable ? 'Hazır' : 'Bağlanıyor…'

  return (
    <div className="conversation" data-testid="conversation">
      <div className="conv-rows">
        {rows.length === 0 && (
          <div className="conv-empty">
            <p>Ne yapmak istersin?</p>
            <small>“Sunucu nasıl?” · “PC’yi kilitle” · “Şu tuş neden çalışmadı?”</small>
          </div>
        )}
        {rows.map(r => (
          <div className={`conv-row ${r.role}`} key={r.id}>
            <span className="who">{r.role === 'user' ? 'Sen' : r.role === 'heren' ? 'Heren' : 'Hata'}<span className="mute"> {hhmm(r.ts)}</span></span>
            <span className="text">{r.text}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form className="conv-input" onSubmit={e => { e.preventDefault(); submit() }}>
        <input className="input" aria-label="Heren'e mesaj" value={text} onChange={e => setText(e.target.value)}
          placeholder={hermes.busy ? 'Heren meşgul…' : 'Yaz ya da Heren’e dokunup konuş'} disabled={hermes.busy} />
        <button className="btn primary" type="submit" disabled={hermes.busy || !text.trim()}>Gönder</button>
        <span className="conv-status" data-testid="hermes-status">{status}</span>
      </form>
    </div>
  )
}

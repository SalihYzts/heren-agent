import { useEffect, useState } from 'react'

interface Props {
  fetchCode: () => Promise<{ code: string; ttl_s: number }>
  onClose: () => void
}

export function PairingModal({ fetchCode, onClose }: Props) {
  const [code, setCode] = useState<string | null>(null)
  const [ttl, setTtl] = useState(0)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchCode().then(r => { setCode(r.code); setTtl(Math.round(r.ttl_s)) }).catch(e => setErr(String(e.message ?? e)))
  }, [fetchCode])

  useEffect(() => {
    if (!code) return
    const t = setInterval(() => setTtl(x => Math.max(0, x - 1)), 1000)
    return () => clearInterval(t)
  }, [code])

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="panel-h">Cihaz eşle<span className="count">{ttl > 0 ? `${ttl}s` : ''}</span></div>
        <div className="panel-b">
          {err && <div className="err-line">{err}</div>}
          {code && (
            <>
              <div className="code" data-testid="pairing-code">{ttl > 0 ? code : '——————'}</div>
              <div className="dim mono" style={{ fontSize: 11 }}>
                Hedef makinede:<br />
                <span style={{ color: 'var(--fg)' }}>nero-agent --core ws://&lt;bu-sunucu&gt;:8700/ws/agent --pair {ttl > 0 ? code : '…'}</span><br /><br />
                Kod tek kullanımlık; agent bağlanınca cihaz listede belirir.
              </div>
            </>
          )}
          <div style={{ marginTop: 12 }}><button className="btn" onClick={onClose}>Kapat</button></div>
        </div>
      </div>
    </div>
  )
}

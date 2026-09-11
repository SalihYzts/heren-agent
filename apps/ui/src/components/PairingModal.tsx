import { useEffect, useState } from 'react'

export interface PairingInfo {
  code: string
  ttl_s: number
  agent_urls: string[]
  ca_file: string | null
  agent_download: string
}

interface Props {
  fetchCode: () => Promise<PairingInfo>
  onClose: () => void
  apiBase: string
  apiKey: string
}

/** Step-by-step: download the agent + cert from this core, run one command on the other machine. */
export function PairingModal({ fetchCode, onClose, apiBase, apiKey }: Props) {
  const [info, setInfo] = useState<PairingInfo | null>(null)
  const [ttl, setTtl] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    fetchCode().then(r => { setInfo(r); setTtl(Math.round(r.ttl_s)) }).catch(e => setErr(String(e.message ?? e)))
  }, [fetchCode])

  useEffect(() => {
    if (!info) return
    const t = setInterval(() => setTtl(x => Math.max(0, x - 1)), 1000)
    return () => clearInterval(t)
  }, [info])

  const url = info?.agent_urls[0] ?? ''
  const tls = url.startsWith('wss://')
  const code = ttl > 0 ? info?.code ?? '' : '……'
  const command = info
    ? `chmod +x heren-agent-linux-amd64 && ./heren-agent-linux-amd64 -core ${url}${tls ? ' -ca-file ./heren-cert.pem' : ''} -name "$(hostname)" -pair ${code}`
    : ''

  const dl = (path: string) => `${apiBase}${path}?token=${encodeURIComponent(apiKey)}`   // <a download> cannot send a header

  const copy = () => {
    void navigator.clipboard?.writeText(command).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
  }

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
        <div className="panel-h">Cihaz eşle<span className="count">{ttl > 0 ? `${ttl}s` : ''}</span></div>
        <div className="panel-b">
          {err && <div className="err-line">{err}</div>}
          {info && (
            <ol className="steps">
              <li>
                <strong>Diğer makine aynı Wi‑Fi’de olsun.</strong> Bu bilgisayara şu adreslerden biriyle ulaşacak:
                <div className="mono dim" style={{ fontSize: 11 }}>{info.agent_urls.join('  ·  ')}</div>
              </li>
              <li>
                <strong>Oradan indir</strong> (bu sayfayı o makinede açıp tıkla, ya da dosyaları kopyala):
                <div className="row">
                  <a className="btn" href={dl(info.agent_download)} download>Ajanı indir (Linux x86‑64)</a>
                  {tls && <a className="btn" href={dl('/api/access/cert.pem')} download="heren-cert.pem">Sertifikayı indir</a>}
                </div>
                {tls && <div className="dim" style={{ fontSize: 12 }}>Sertifika gerekli: bu sunucu kendi imzalı https kullanıyor, ajan sadece o sertifikaya güvenir.</div>}
              </li>
              <li>
                <strong>O makinede, indirdiğin klasörde çalıştır:</strong>
                <pre className="cmd" data-testid="pairing-command">{command}</pre>
                <div className="row">
                  <button className="btn" onClick={copy} disabled={ttl <= 0}>{copied ? 'Kopyalandı' : 'Kopyala'}</button>
                  <span className="dim" style={{ fontSize: 12 }}>Kod <span className="mono" data-testid="pairing-code">{code}</span> tek kullanımlık; bağlanınca cihaz listede belirir.</span>
                </div>
              </li>
              <li className="dim" style={{ fontSize: 12 }}>
                Kalıcı çalışması için <span className="mono">deploy/</span> altındaki systemd servis örneğine bak.
              </li>
            </ol>
          )}
          <div style={{ marginTop: 12 }}><button className="btn" onClick={onClose}>Kapat</button></div>
        </div>
      </div>
    </div>
  )
}

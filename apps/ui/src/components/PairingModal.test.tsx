import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PairingModal } from './PairingModal'

const resp = {
  code: '123456', ttl_s: 120,
  agent_urls: ['wss://192.168.1.150:8701/ws/agent', 'wss://pc.local:8701/ws/agent'],
  ca_file: '/srv/heren/data/tls/cert.pem',
  agent_download: '/api/agent/heren-agent-linux-amd64',
}

describe('PairingModal', () => {
  it('prints the exact agent command for this core: real wss url, pinned cert, the code', async () => {
    render(<PairingModal fetchCode={async () => resp} onClose={() => {}} apiBase="" apiKey="k" />)
    const cmd = await screen.findByTestId('pairing-command')
    expect(cmd.textContent).toContain('-core wss://192.168.1.150:8701/ws/agent')
    expect(cmd.textContent).toContain('-ca-file ./heren-cert.pem')
    expect(cmd.textContent).toContain('-pair 123456')
    expect(screen.getByRole('link', { name: /Ajanı indir/ })).toHaveAttribute('href', '/api/agent/heren-agent-linux-amd64?token=k')
    expect(screen.getByRole('link', { name: /Sertifikayı indir/ })).toHaveAttribute('href', '/api/access/cert.pem?token=k')
    expect(screen.getByText(/aynı Wi‑Fi/i)).toBeInTheDocument()
  })

  it('without TLS: ws url, no cert step', async () => {
    render(<PairingModal fetchCode={async () => ({ ...resp, agent_urls: ['ws://192.168.1.150:8700/ws/agent'], ca_file: null })} onClose={() => {}} apiBase="" apiKey="k" />)
    const cmd = await screen.findByTestId('pairing-command')
    expect(cmd.textContent).toContain('-core ws://192.168.1.150:8700/ws/agent')
    expect(cmd.textContent).not.toContain('-ca-file')
    await waitFor(() => expect(screen.queryByRole('link', { name: /Sertifikayı indir/ })).toBeNull())
  })

  it('copies the command on click', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<PairingModal fetchCode={async () => resp} onClose={() => {}} apiBase="" apiKey="k" />)
    ;(await screen.findByRole('button', { name: /Kopyala/ })).click()
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('-pair 123456')))
  })
})

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Approvals } from './Approvals'
import type { Approval } from '../lib/types'

const a: Approval = {
  request_id: 'r1', device_id: 'main-pc', action: 'shutdown', params: {}, risk: 'high',
  requested_by: 'hermes', expires_at: Date.now() / 1000 + 45,
}

describe('Approvals', () => {
  it('shows who asks what on which device, with risk', () => {
    render(<Approvals approvals={[a]} devices={{ 'main-pc': { name: 'MAIN PC' } as any }} onApprove={() => {}} onDeny={() => {}} />)
    expect(screen.getByText(/hermes/)).toBeInTheDocument()
    expect(screen.getByText('shutdown')).toBeInTheDocument()
    expect(screen.getByText('MAIN PC')).toBeInTheDocument()
    expect(screen.getByText('high')).toBeInTheDocument()
  })

  it('approve and deny call back with the request id', () => {
    const onApprove = vi.fn(); const onDeny = vi.fn()
    render(<Approvals approvals={[a]} devices={{}} onApprove={onApprove} onDeny={onDeny} />)
    fireEvent.click(screen.getByRole('button', { name: /onayla/i }))
    expect(onApprove).toHaveBeenCalledWith('r1')
    fireEvent.click(screen.getByRole('button', { name: /reddet/i }))
    expect(onDeny).toHaveBeenCalledWith('r1')
  })

  it('renders an empty state when nothing is pending', () => {
    render(<Approvals approvals={[]} devices={{}} onApprove={() => {}} onDeny={() => {}} />)
    expect(screen.getByText(/bekleyen onay yok/i)).toBeInTheDocument()
  })

  it('shows params like the boot entry', () => {
    render(<Approvals approvals={[{ ...a, action: 'set_next_boot', params: { entry: '0000' } }]} devices={{}} onApprove={() => {}} onDeny={() => {}} />)
    expect(screen.getByText(/entry=0000/)).toBeInTheDocument()
  })
})

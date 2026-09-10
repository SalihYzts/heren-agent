import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DeviceCard } from './DeviceCard'
import type { Device } from '../lib/types'

const dev: Device = {
  device_id: 'main-pc', name: 'MAIN PC', platform: 'linux', public_key: 'ab', status: 'online',
  last_seen: 1, capabilities: ['get_status', 'get_boot_entries', 'restart', 'shutdown', 'lock', 'set_next_boot'],
}

describe('DeviceCard', () => {
  it('renders name, status and live metrics', () => {
    render(<DeviceCard device={dev} metrics={{ load1: 1.2, ram_pct: 62, ram_total_mb: 16000 }} onAction={() => {}} bootEntries={undefined} />)
    expect(screen.getByText('MAIN PC')).toBeInTheDocument()
    expect(screen.getByText(/online/i)).toBeInTheDocument()
    expect(screen.getByText('62%')).toBeInTheDocument()
  })

  it('only offers actions the device declared, high-risk ones styled as such', () => {
    render(<DeviceCard device={dev} metrics={{}} onAction={() => {}} bootEntries={undefined} />)
    expect(screen.getByRole('button', { name: /shutdown/i })).toHaveClass('high')
    expect(screen.getByRole('button', { name: /^lock$/i })).not.toHaveClass('high')
    expect(screen.queryByRole('button', { name: /launch_app/i })).toBeNull()
  })

  it('disables action buttons when offline', () => {
    render(<DeviceCard device={{ ...dev, status: 'offline' }} metrics={{}} onAction={() => {}} bootEntries={undefined} />)
    expect(screen.getByRole('button', { name: /shutdown/i })).toBeDisabled()
  })

  it('clicking an action calls back with device id, action and params', () => {
    const onAction = vi.fn()
    render(<DeviceCard device={dev} metrics={{}} onAction={onAction} bootEntries={undefined} />)
    fireEvent.click(screen.getByRole('button', { name: /restart/i }))
    expect(onAction).toHaveBeenCalledWith('main-pc', 'restart', {})
  })

  it('boot entries become "switch to" buttons that request set_next_boot', () => {
    const onAction = vi.fn()
    render(<DeviceCard device={dev} metrics={{}} onAction={onAction}
      bootEntries={[{ id: '0000', title: 'Windows Boot Manager', default: false }, { id: '0001', title: 'Limine', default: true }]} />)
    fireEvent.click(screen.getByRole('button', { name: /Windows Boot Manager/ }))
    expect(onAction).toHaveBeenCalledWith('main-pc', 'set_next_boot', { entry: '0000' })
  })
})

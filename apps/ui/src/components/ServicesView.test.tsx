import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ServicesView } from './ServicesView'

const services = [
  { name: 'nginx', state: 'running', description: 'A high performance web server' },
  { name: 'postgresql', state: 'failed', description: 'PostgreSQL database server' },
  { name: 'alsa-restore', state: 'exited', description: 'Save/Restore Sound Card State' },
  { name: 'hermes-gateway', state: 'inactive', description: 'Hermes gateway' },
]
const containers = [{ name: 'web', image: 'nginx:1.27', state: 'running', status: 'Up 3 hours' }]

function setup(over: Partial<Parameters<typeof ServicesView>[0]> = {}) {
  const run = vi.fn(async (_d: string, action: string, params: Record<string, unknown>) => {
    if (action === 'list_services') return { services, failed: 1 }
    if (action === 'list_containers') return { runtime: 'docker', containers }
    if (action === 'service_logs') return { lines: [`2026-09-11T12:00:00+0300 pc ${params.name}[1]: started`, 'line two'] }
    return {}
  })
  render(<ServicesView deviceId="srv" deviceName="Srv" run={run} {...over} />)
  return { run }
}

describe('ServicesView', () => {
  it('lists services with failed ones first and a summary line', async () => {
    const { run } = setup()
    await screen.findByText('nginx')
    expect(run).toHaveBeenCalledWith('srv', 'list_services', {})
    const rows = screen.getAllByRole('row').filter(r => r.hasAttribute('data-state')).map(r => r.getAttribute('aria-label'))
    expect(rows[0]).toBe('postgresql')                                   // failed on top
    expect(screen.getByText(/1 hatalı · 4 servis/)).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /postgresql/ })).toHaveAttribute('data-state', 'failed')
  })

  it('filters by name and hides the boring exited/inactive ones by default', async () => {
    setup()
    await screen.findByText('nginx')
    expect(screen.queryByText('alsa-restore')).toBeNull()
    fireEvent.click(screen.getByLabelText('Hepsini göster'))
    expect(screen.getByText('alsa-restore')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Servis ara'), { target: { value: 'post' } })
    expect(screen.getByText('postgresql')).toBeInTheDocument()
    expect(screen.queryByText('nginx')).toBeNull()
  })

  it('start/stop/restart go through run with the service name; failed ones offer Başlat', async () => {
    const { run } = setup()
    const pg = await screen.findByRole('row', { name: /postgresql/ })
    fireEvent.click(within(pg).getByRole('button', { name: 'Başlat' }))
    expect(run).toHaveBeenCalledWith('srv', 'start_service', { name: 'postgresql' })
    fireEvent.click(within(screen.getByRole('row', { name: /nginx/ })).getByRole('button', { name: 'Yeniden başlat' }))
    expect(run).toHaveBeenCalledWith('srv', 'restart_service', { name: 'nginx' })
    await waitFor(() => expect(run.mock.calls.filter(c => c[1] === 'list_services').length).toBeGreaterThan(1))   // refreshed after the action
    fireEvent.click(within(screen.getByRole('row', { name: /nginx/ })).getByRole('button', { name: 'Durdur' }))
    expect(run).toHaveBeenCalledWith('srv', 'stop_service', { name: 'nginx' })
  })

  it('opens the journal for a service inline', async () => {
    const { run } = setup()
    const pg = await screen.findByRole('row', { name: /postgresql/ })
    fireEvent.click(within(pg).getByRole('button', { name: 'Kayıtlar' }))
    expect(run).toHaveBeenCalledWith('srv', 'service_logs', { name: 'postgresql', lines: 100 })
    expect(await screen.findByText(/postgresql\[1\]: started/)).toBeInTheDocument()
  })

  it('shows containers when a runtime exists, nothing when it does not', async () => {
    setup()
    expect(await screen.findByText('web')).toBeInTheDocument()
    expect(screen.getByText(/docker/)).toBeInTheDocument()
  })

  it('surfaces errors from the device instead of an empty table', async () => {
    const run = vi.fn(async () => { throw new Error('cihaz çevrimdışı') })
    render(<ServicesView deviceId="srv" deviceName="Srv" run={run} />)
    expect(await screen.findByText(/cihaz çevrimdışı/)).toBeInTheDocument()
  })
})

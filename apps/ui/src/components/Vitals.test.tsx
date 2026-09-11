import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Sparkline, sparkPath } from './Sparkline'
import { Vitals, fmtBytes, fmtUptime } from './Vitals'

describe('sparkPath', () => {
  it('scales values into the box, newest at the right, and copes with flat/empty series', () => {
    expect(sparkPath([], 100, 20)).toBe('')
    expect(sparkPath([5], 100, 20)).toBe('')                      // one point = no line
    const d = sparkPath([0, 50, 100], 100, 20, 100)
    expect(d).toMatch(/^M0,20/)                                     // 0 → bottom
    expect(d).toContain('100,0')                                    // 100 (= max) → top
    expect(sparkPath([40, 40, 40], 100, 20)).toContain(',10')       // flat, no max → mid-height (headroom), not NaN
    expect(sparkPath([40, 40, 40], 100, 20)).not.toContain('NaN')
  })
  it('renders an svg with the series length as a data attribute', () => {
    const { container } = render(<Sparkline values={[1, 2, 3]} max={100} />)
    expect(container.querySelector('svg')).toHaveAttribute('data-points', '3')
  })
})

describe('formatters', () => {
  it('bytes and uptime read like a human wrote them', () => {
    expect(fmtBytes(512)).toBe('512 B')
    expect(fmtBytes(1536)).toBe('1.5 KB')
    expect(fmtBytes(2.5 * 1024 ** 3)).toBe('2.5 GB')
    expect(fmtUptime(59)).toBe('59 sn')
    expect(fmtUptime(3600 * 5 + 60 * 7)).toBe('5 sa 7 dk')
    expect(fmtUptime(86400 * 3 + 3600 * 2)).toBe('3 g 2 sa')
  })
})

describe('Vitals', () => {
  const latest = { cpu_pct: 12, ram_pct: 59, ram_total_mb: 15201, swap_pct: 1, disk_pct: 53, temp_c: 72, load1: 1.07, uptime_s: 7404,
    net_rx_bytes: 802283326, net_tx_bytes: 167323320, disks: [{ mount: '/', pct: 53, used_gb: 431, total_gb: 950 }, { mount: '/srv', pct: 91, used_gb: 9.1, total_gb: 10 }], ts: 1 }
  const history = [{ ts: 1, cpu_pct: 5, ram_pct: 50, disk_pct: 53 }, { ts: 2, cpu_pct: 12, ram_pct: 59, disk_pct: 53 }]

  it('shows real numbers, every mount, and flags the mount that is nearly full', () => {
    render(<Vitals latest={latest} history={history} />)
    expect(screen.getByLabelText('CPU')).toHaveTextContent('12%')
    expect(screen.getByLabelText('RAM')).toHaveTextContent('59%')
    expect(screen.getByLabelText('RAM')).toHaveTextContent('14.8 GB')
    expect(screen.getByLabelText('Sıcaklık')).toHaveTextContent('72°C')
    expect(screen.getByLabelText('Çalışma süresi')).toHaveTextContent('2 sa 3 dk')
    expect(screen.getByLabelText('Ağ')).toHaveTextContent('765.1 MB')
    const srv = screen.getByLabelText('Disk /srv')
    expect(srv).toHaveTextContent('91%')
    expect(srv).toHaveAttribute('data-level', 'critical')
    expect(screen.getByLabelText('Disk /')).toHaveAttribute('data-level', 'ok')
    expect(screen.getAllByRole('img', { name: /son bir saat/i })).toHaveLength(3)   // cpu, ram, disk sparklines
  })

  it('says so when there is no sample yet instead of drawing dashes', () => {
    render(<Vitals latest={undefined} history={[]} />)
    expect(screen.getByText(/henüz ölçüm yok/i)).toBeInTheDocument()
  })

  it('warns at 80 and screams at 90 on RAM and CPU too', () => {
    render(<Vitals latest={{ ...latest, cpu_pct: 85, ram_pct: 95 }} history={[]} />)
    expect(screen.getByLabelText('CPU')).toHaveAttribute('data-level', 'warn')
    expect(screen.getByLabelText('RAM')).toHaveAttribute('data-level', 'critical')
  })
})

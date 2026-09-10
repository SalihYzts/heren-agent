import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Waveform, wavePath } from './Waveform'

describe('wavePath', () => {
  it('maps levels to a symmetric path across the full width, centred vertically', () => {
    const d = wavePath([0, 0.5, 1], 300, 100)
    expect(d.startsWith('M')).toBe(true)
    // three points → x at 0, 150, 300; last level 1 → full half-height 50 above/below 50
    expect(d).toContain('300,0')
    expect(d).toContain('300,100')
    expect(d).toContain('0,50')
  })
  it('clamps levels into 0..1 and tolerates an empty array', () => {
    expect(wavePath([], 100, 40)).toBe('')
    expect(wavePath([5, -3], 100, 40)).toContain('0,0')       // 5 → 1 → top
  })
})

describe('Waveform', () => {
  it('renders an svg with a role and hides itself when idle', () => {
    const { container, rerender } = render(<Waveform levels={[0.2, 0.6]} active tone="user" />)
    const svg = container.querySelector('svg')!
    expect(svg).toHaveAttribute('data-tone', 'user')
    expect(svg).toHaveAttribute('data-active', 'true')
    rerender(<Waveform levels={[]} active={false} tone="heren" />)
    expect(container.querySelector('svg')).toHaveAttribute('data-active', 'false')
    expect(container.querySelector('svg')).toHaveAttribute('data-tone', 'heren')
  })
})

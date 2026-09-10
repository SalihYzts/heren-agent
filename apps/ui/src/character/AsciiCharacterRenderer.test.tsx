import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AsciiCharacterRenderer } from './AsciiCharacterRenderer'
import type { AsciiAssetPack } from './ascii'

const pack: AsciiAssetPack = {
  cell: { cols: 5, rows: 2 },
  fps: 4,
  animations: {
    'idle.neutral': { frames: ['(o o)\n ---', '(- -)\n ---'] },
    'thinking': { frames: ['(o o)\n ..'], fps: 1 },
    'default': { frames: ['[???]'] },
  },
}

const frameText = () => (screen.getByTestId('ascii-frame') as HTMLPreElement).textContent

describe('AsciiCharacterRenderer', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('renders the first frame in a <pre> with monospace and a fixed cell box', () => {
    render(<AsciiCharacterRenderer pack={pack} activity="idle" mood="neutral" />)
    const pre = screen.getByTestId('ascii-frame') as HTMLPreElement
    expect(pre.tagName).toBe('PRE')
    expect(pre.textContent).toBe('(o o)\n --- ')
    expect(pre.style.width).toBe('5ch')
    expect(pre.style.height).toBe('2lh')
  })

  it('cycles frames at the animation fps', () => {
    render(<AsciiCharacterRenderer pack={pack} activity="idle" mood="neutral" />)
    expect(frameText()).toBe('(o o)\n --- ')
    act(() => { vi.advanceTimersByTime(250) })
    expect(frameText()).toBe('(- -)\n --- ')
    act(() => { vi.advanceTimersByTime(250) })
    expect(frameText()).toBe('(o o)\n --- ')
  })

  it('switching state restarts at frame 0 of the new animation', () => {
    const { rerender } = render(<AsciiCharacterRenderer pack={pack} activity="idle" mood="neutral" />)
    act(() => { vi.advanceTimersByTime(250) })
    rerender(<AsciiCharacterRenderer pack={pack} activity="thinking" mood="neutral" />)
    expect(frameText()).toBe('(o o)\n ..  ')
    act(() => { vi.advanceTimersByTime(250) })
    expect(frameText()).toBe('(o o)\n ..  ') // 1 fps: no change yet
  })

  it('falls back to default art and marks it', () => {
    render(<AsciiCharacterRenderer pack={pack} activity="sleeping" mood="sleepy" />)
    expect(frameText()).toBe('[???]\n     ')
    expect(screen.getByTestId('ascii-frame').dataset.fallback).toBe('true')
  })

  it('single-frame animations do not schedule a timer', () => {
    render(<AsciiCharacterRenderer pack={pack} activity="thinking" mood="neutral" />)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('exposes activity/mood as data attributes for styling', () => {
    render(<AsciiCharacterRenderer pack={pack} activity="idle" mood="neutral" />)
    const pre = screen.getByTestId('ascii-frame')
    expect(pre.dataset.activity).toBe('idle')
    expect(pre.dataset.mood).toBe('neutral')
  })
})

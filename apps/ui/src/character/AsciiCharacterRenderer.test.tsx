import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AsciiCharacterRenderer, fitFontSize } from './AsciiCharacterRenderer'
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
    expect(pre.style.width).toBe('max-content')
    expect(pre.style.minWidth).toBe('5ch')
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

// ---------------------------------------------------------------- v2: intro → loop, fit, presentation

const v2: AsciiAssetPack = {
  cell: { cols: 2, rows: 1 },
  fps: 10,
  frames: { a: 'A', b: 'B', c: 'C', d: 'D' },
  animations: {
    'thinking': { intro: ['a', 'b'], loop: ['c', 'd'] },
    'sleeping': { loop: ['a'] },
    'default': { frames: ['?'] },
  },
}

describe('AsciiCharacterRenderer v2', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('uses a readable base font before scaling, avoiding tiny-font glyph rounding', () => {
    render(<AsciiCharacterRenderer pack={v2} activity="sleeping" mood="neutral" />)
    expect(screen.getByTestId('ascii-frame').style.fontSize).toBe('16px')
  })

  it('plays the intro once then cycles only the loop', () => {
    render(<AsciiCharacterRenderer pack={v2} activity="thinking" mood="neutral" />)
    const seen = [frameText()]
    for (let i = 0; i < 5; i++) { act(() => { vi.advanceTimersByTime(100) }); seen.push(frameText()) }
    expect(seen).toEqual(['A ', 'B ', 'C ', 'D ', 'C ', 'D '])
  })

  it('exposes the resolved animation name and phase (intro/loop) for styling and tests', () => {
    render(<AsciiCharacterRenderer pack={v2} activity="thinking" mood="neutral" />)
    const pre = screen.getByTestId('ascii-frame')
    expect(pre.dataset.anim).toBe('thinking')
    expect(pre.dataset.phase).toBe('intro')
    act(() => { vi.advanceTimersByTime(200) })
    expect(pre.dataset.phase).toBe('loop')
  })

  it('applies a presentation class per activity/mood and a dim tint while sleeping', () => {
    const { rerender } = render(<AsciiCharacterRenderer pack={v2} activity="sleeping" mood="sleepy" />)
    const pre = screen.getByTestId('ascii-frame')
    expect(pre.className).toContain('is-sleeping')
    expect(pre.className).toContain('mood-sleepy')
    rerender(<AsciiCharacterRenderer pack={v2} activity="thinking" mood="neutral" />)
    expect(pre.className).not.toContain('is-sleeping')
  })

  it('scales the font so the whole cell fits the given box (fitFontSize)', () => {
    // 140 cols × 122 rows into 420×366 px with a 0.6 char aspect → limited by width: 420/(140*0.6)=5px
    expect(fitFontSize({ cols: 140, rows: 122 }, 420, 366, 0.6, 1.2)).toBeCloseTo(2.5, 5)
    // wide box: limited by height: 366/(122*1.2)=2.5
    expect(fitFontSize({ cols: 140, rows: 122 }, 4000, 366, 0.6, 1.2)).toBeCloseTo(2.5, 5)
    expect(fitFontSize({ cols: 10, rows: 2 }, 0, 0, 0.6, 1.2)).toBe(0)
  })

  it('low energy slows the animation (fps multiplier)', () => {
    render(<AsciiCharacterRenderer pack={v2} activity="thinking" mood="neutral" energy={0.1} />)
    expect(frameText()).toBe('A ')
    act(() => { vi.advanceTimersByTime(100) })
    expect(frameText()).toBe('A ')   // half speed: still on the first frame
    act(() => { vi.advanceTimersByTime(100) })
    expect(frameText()).toBe('B ')
  })
})

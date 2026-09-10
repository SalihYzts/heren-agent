import { describe, expect, it } from 'vitest'
import { normalizeFrames, resolveAnimation, type AsciiAssetPack } from './ascii'

const pack: AsciiAssetPack = {
  cell: { cols: 6, rows: 3 },
  fps: 2,
  animations: {
    'idle.neutral': { frames: ['(o o)\n', ' ---\n'], fps: 1 },
    'idle': { frames: ['(- -)'] },
    'sleeping.sleepy': { frames: ['(- -)z', '(- -)Z'] },
    'default': { frames: ['(?)'] },
  },
}

describe('resolveAnimation', () => {
  it('prefers exact activity.mood match', () => {
    const a = resolveAnimation(pack, 'idle', 'neutral')
    expect(a.key).toBe('idle.neutral')
    expect(a.fps).toBe(1)
  })
  it('falls back to activity-only, then default, and reports it', () => {
    expect(resolveAnimation(pack, 'idle', 'happy').key).toBe('idle')
    const d = resolveAnimation(pack, 'thinking', 'neutral')
    expect(d.key).toBe('default')
    expect(d.fallback).toBe(true)
  })
  it('sleeping.sleepy resolves and inherits pack fps when the animation has none', () => {
    const a = resolveAnimation(pack, 'sleeping', 'sleepy')
    expect(a.frames).toHaveLength(2)
    expect(a.fps).toBe(2)
  })
  it('never returns an empty frame list even for an empty pack', () => {
    const a = resolveAnimation({ cell: { cols: 3, rows: 1 }, fps: 1, animations: {} }, 'idle', 'neutral')
    expect(a.frames.length).toBeGreaterThan(0)
    expect(a.fallback).toBe(true)
  })
})

describe('normalizeFrames', () => {
  it('pads every frame to cell size so the box never jumps, preserving inner whitespace', () => {
    const out = normalizeFrames(['(o o)\n ---', ' x'], { cols: 6, rows: 3 })
    expect(out[0].split('\n')).toEqual(['(o o) ', ' ---  ', '      '])
    expect(out[1].split('\n')).toEqual([' x    ', '      ', '      '])
  })
  it('clips frames that exceed the cell', () => {
    const out = normalizeFrames(['123456789\na\nb\nc\nd'], { cols: 4, rows: 2 })
    expect(out[0]).toBe('1234\na   ')
  })
  it('keeps tabs-free leading spaces exactly (whitespace is the drawing)', () => {
    const out = normalizeFrames(['   ^\n  / \\'], { cols: 5, rows: 2 })
    expect(out[0]).toBe('   ^ \n  / \\')
  })
})

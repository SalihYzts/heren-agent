import { describe, expect, it } from 'vitest'
import { nextFrameIndex, normalizeFrames, resolveAnimation, type AsciiAssetPack } from './ascii'

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

// ---------------------------------------------------------------- pack v2: named frames + sequences

const v2: AsciiAssetPack = {
  cell: { cols: 4, rows: 1 },
  fps: 8,
  frames: { a: 'AAAA', b: 'BBBB', c: 'CCCC', d: 'DDDD' },
  animations: {
    // sequences reference named frames; intro plays once, loop repeats
    'thinking': { intro: ['a', 'b'], loop: ['c', 'd', 'c'] },
    'speaking': { loop: ['a', 'b'], fps: 2 },
    'idle': { frames: ['(o)'] },               // v1 inline frames still work
    'waking': { intro: ['d'] },                 // intro only: ends holding the last frame
    'default': { frames: ['????'] },
  },
}

describe('resolveAnimation with named frames and intro/loop', () => {
  it('expands sequences into normalized frames and reports the loop start', () => {
    const a = resolveAnimation(v2, 'thinking', 'neutral')
    expect(a.frames).toEqual(['AAAA', 'BBBB', 'CCCC', 'DDDD', 'CCCC'])
    expect(a.loopStart).toBe(2)
    expect(a.fps).toBe(8)
  })
  it('loop-only sequences start looping at 0', () => {
    const a = resolveAnimation(v2, 'speaking', 'neutral')
    expect(a.frames).toEqual(['AAAA', 'BBBB'])
    expect(a.loopStart).toBe(0)
    expect(a.fps).toBe(2)
  })
  it('intro-only sequences hold the last frame (loopStart = last index)', () => {
    const a = resolveAnimation(v2, 'waking', 'neutral')
    expect(a.frames).toEqual(['DDDD'])
    expect(a.loopStart).toBe(0)
  })
  it('inline v1 frames keep working and loop from 0', () => {
    const a = resolveAnimation(v2, 'idle', 'neutral')
    expect(a.frames).toEqual(['(o) '])
    expect(a.loopStart).toBe(0)
  })
  it('an unknown frame name is skipped, never crashes, and is reported', () => {
    const p: AsciiAssetPack = { ...v2, animations: { 'idle': { loop: ['a', 'nope', 'b'] } } }
    const a = resolveAnimation(p, 'idle', 'neutral')
    expect(a.frames).toEqual(['AAAA', 'BBBB'])
    expect(a.missing).toEqual(['nope'])
  })
})

describe('nextFrameIndex', () => {
  it('runs through the intro once then cycles the loop', () => {
    const seq = [0, 1, 2, 3, 4].map(i => nextFrameIndex(i, 5, 2))
    expect(seq).toEqual([1, 2, 3, 4, 2])
  })
  it('a single frame stays put', () => {
    expect(nextFrameIndex(0, 1, 0)).toBe(0)
  })
})

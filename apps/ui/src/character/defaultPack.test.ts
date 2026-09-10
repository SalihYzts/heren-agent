import { describe, expect, it } from 'vitest'
import { defaultPack } from './defaultPack'
import { resolveAnimation } from './ascii'

const ACTIVITIES = ['idle', 'listening', 'thinking', 'speaking', 'working', 'sleeping', 'waking']
const MOODS = ['neutral', 'happy', 'sleepy', 'annoyed', 'confused']

describe('defaultPack', () => {
  it('has real (non-fallback) art for every engine activity', () => {
    for (const a of ACTIVITIES) {
      expect(resolveAnimation(defaultPack, a, 'neutral').fallback, a).toBe(false)
    }
  })
  it('resolves every activity×mood combination to something drawable', () => {
    for (const a of ACTIVITIES) for (const m of MOODS) {
      const r = resolveAnimation(defaultPack, a, m)
      expect(r.frames.length).toBeGreaterThan(0)
      for (const f of r.frames) {
        const lines = f.split('\n')
        expect(lines).toHaveLength(defaultPack.cell.rows)
        for (const l of lines) expect(l).toHaveLength(defaultPack.cell.cols)
      }
    }
  })
  it('no raw frame exceeds the cell (art would be silently clipped)', () => {
    for (const [key, anim] of Object.entries(defaultPack.animations)) {
      for (const f of anim.frames) {
        const lines = f.split('\n')
        expect(lines.length, key).toBeLessThanOrEqual(defaultPack.cell.rows)
        for (const l of lines) expect(l.length, `${key}: "${l}"`).toBeLessThanOrEqual(defaultPack.cell.cols)
      }
    }
  })
  it('every multi-frame animation actually changes between frames', () => {
    for (const [key, anim] of Object.entries(defaultPack.animations)) {
      if (anim.frames.length > 1) expect(new Set(anim.frames).size, key).toBeGreaterThan(1)
    }
  })
})

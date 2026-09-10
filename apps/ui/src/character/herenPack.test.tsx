import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import pack from '../../public/character/heren.json'
import { AsciiCharacterRenderer } from './AsciiCharacterRenderer'
import { resolveAnimation } from './ascii'
import { validatePack } from './loadPack'

const activities = ['idle', 'listening', 'thinking', 'working', 'speaking', 'waking', 'sleeping']
const moods = ['neutral', 'happy', 'sleepy', 'annoyed', 'confused']

describe('shipped Heren art', () => {
  it('contains valid, uniformly sized frames', () => {
    expect(validatePack(pack)).toBeNull()
    expect(Object.keys(pack.frames)).toHaveLength(28)
    for (const frame of Object.values(pack.frames)) {
      const rows = frame.split('\n')
      expect(rows).toHaveLength(pack.cell.rows)
      expect(rows.every(row => row.length === pack.cell.cols)).toBe(true)
    }
  })
  for (const activity of activities) for (const mood of moods) {
    it(`renders ${activity}.${mood} without fallback or missing frames`, () => {
      const animation = resolveAnimation(pack, activity, mood)
      expect(animation.fallback).toBe(false)
      expect(animation.missing).toEqual([])
      expect(animation.frames.length).toBeGreaterThan(0)
      const { unmount } = render(<AsciiCharacterRenderer pack={pack} activity={activity} mood={mood} />)
      expect(screen.getByTestId('ascii-frame').textContent).toBe(animation.frames[0])
      unmount()
    })
  }
  it('freezes sleeping while speaking has an intro and repeating tail', () => {
    expect(resolveAnimation(pack, 'sleeping', 'sleepy').frames).toHaveLength(1)
    const speaking = resolveAnimation(pack, 'speaking', 'neutral')
    expect(speaking.loopStart).toBe(8)
    expect(speaking.frames.length).toBeGreaterThan(speaking.loopStart)
  })
})

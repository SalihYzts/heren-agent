import { describe, expect, it } from 'vitest'
import { SilenceDetector } from './silence'

// feed(level, nowMs) → 'send' when the user spoke and then went quiet for `holdMs`
describe('SilenceDetector', () => {
  const det = () => new SilenceDetector({ threshold: 0.05, holdMs: 1500, minSpeechMs: 300, maxMs: 20000 })

  it('does not fire before the user has actually spoken (mic just opened, room is quiet)', () => {
    const d = det()
    for (let t = 0; t < 5000; t += 100) expect(d.feed(0.01, t)).toBeNull()
  })

  it('fires once after speech followed by holdMs of silence', () => {
    const d = det()
    for (let t = 0; t < 800; t += 100) expect(d.feed(0.4, t)).toBeNull()        // talking (last speech at 700)
    for (let t = 800; t < 2200; t += 100) expect(d.feed(0.01, t)).toBeNull()    // quiet, not yet
    expect(d.feed(0.01, 2200)).toBe('send')                                        // 700 + 1500
    expect(d.feed(0.01, 2300)).toBeNull()                                          // once
  })

  it('a short blip is not speech; a pause inside speech does not send', () => {
    const d = det()
    d.feed(0.4, 0); d.feed(0.4, 100)                                               // 200 ms blip
    for (let t = 200; t < 3000; t += 100) expect(d.feed(0.01, t)).toBeNull()
    const e = det()
    for (let t = 0; t < 600; t += 100) e.feed(0.4, t)
    for (let t = 600; t < 1500; t += 100) e.feed(0.01, t)                          // 900 ms pause
    for (let t = 1500; t < 2100; t += 100) e.feed(0.4, t)                          // resumes
    for (let t = 2100; t < 3500; t += 100) expect(e.feed(0.01, t)).toBeNull()
    expect(e.feed(0.01, 3600)).toBe('send')
  })

  it('gives up with "timeout" when nothing was said for maxMs', () => {
    const d = det()
    let r: string | null = null
    for (let t = 0; t <= 20000 && !r; t += 500) r = d.feed(0.01, t)
    expect(r).toBe('timeout')
  })
})

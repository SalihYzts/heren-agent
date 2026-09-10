// SpeechQueue: plays voice.speech clips strictly in (run_id, seq) order through an
// injected Player; voice.stopped cuts the current clip and clears the rest.
import { describe, expect, it, vi } from 'vitest'
import { SpeechQueue, type Player, audioPlayer } from './speechQueue'

class FakePlayer implements Player {
  played: string[] = []
  private resolvers: Array<() => void> = []
  stopped = 0
  play(url: string): Promise<void> {
    this.played.push(url)
    return new Promise(res => this.resolvers.push(res))
  }
  stop() { this.stopped++; this.resolvers.splice(0).forEach(r => r()) }
  finishCurrent() { this.resolvers.shift()?.() }
}

const speech = (run_id: string, seq: number) =>
  ({ type: 'voice.speech', payload: { run_id, seq, clip_id: `${run_id}-${seq}`, url: `/a/${run_id}-${seq}.wav`, text: 'x', duration_s: 1 }, ts: 0 })

const tick = () => new Promise(r => setTimeout(r, 0))

describe('SpeechQueue', () => {
  it('plays clips one after another, never overlapping', async () => {
    const p = new FakePlayer(); const q = new SpeechQueue(p)
    q.handle(speech('r1', 0)); q.handle(speech('r1', 1)); await tick()
    expect(p.played).toEqual(['/a/r1-0.wav'])
    p.finishCurrent(); await tick()
    expect(p.played).toEqual(['/a/r1-0.wav', '/a/r1-1.wav'])
  })

  it('reorders clips that arrive out of sequence', async () => {
    const p = new FakePlayer(); const q = new SpeechQueue(p)
    q.handle(speech('r1', 1)); await tick()
    expect(p.played).toEqual([])            // waits for seq 0
    q.handle(speech('r1', 0)); await tick()
    expect(p.played).toEqual(['/a/r1-0.wav'])
    p.finishCurrent(); await tick()
    expect(p.played).toEqual(['/a/r1-0.wav', '/a/r1-1.wav'])
  })

  it('a new run does not wait for gaps of the old one', async () => {
    const p = new FakePlayer(); const q = new SpeechQueue(p)
    q.handle(speech('r1', 0)); await tick(); p.finishCurrent(); await tick()
    q.handle(speech('r2', 0)); await tick()
    expect(p.played).toEqual(['/a/r1-0.wav', '/a/r2-0.wav'])
  })

  it('voice.stopped cuts playback and drops the queue', async () => {
    const p = new FakePlayer(); const q = new SpeechQueue(p)
    q.handle(speech('r1', 0)); q.handle(speech('r1', 1)); q.handle(speech('r1', 2)); await tick()
    q.handle({ type: 'voice.stopped', payload: { run_id: 'r1' }, ts: 0 }); await tick()
    expect(p.stopped).toBe(1)
    expect(p.played).toEqual(['/a/r1-0.wav'])
    expect(q.state()).toEqual({ speaking: false, queued: 0 })
  })

  it('reports speaking state changes to a listener', async () => {
    const p = new FakePlayer(); const q = new SpeechQueue(p)
    const seen: boolean[] = []
    q.onChange(s => seen.push(s.speaking))
    q.handle(speech('r1', 0)); await tick()
    p.finishCurrent(); await tick()
    expect(seen).toEqual([true, false])
  })

  it('keeps going after a clip fails to play', async () => {
    const failing: Player = {
      played: [] as string[],
      play(url: string) { (this.played as string[]).push(url); return url.includes('-0') ? Promise.reject(new Error('decode')) : Promise.resolve() },
      stop() {},
    } as Player & { played: string[] }
    const q = new SpeechQueue(failing)
    q.handle(speech('r1', 0)); q.handle(speech('r1', 1)); await tick(); await tick()
    expect((failing as unknown as { played: string[] }).played).toEqual(['/a/r1-0.wav', '/a/r1-1.wav'])
  })
})

describe('audioPlayer level tap', () => {
  it('reports a 0..1 level while a clip plays and 0 when it ends', async () => {
    const levels: number[] = []
    const analyser = { fftSize: 0, getByteTimeDomainData: (a: Uint8Array) => { a.fill(128 + 40) }, connect: vi.fn() }
    const ctx = { createMediaElementSource: () => ({ connect: vi.fn() }), createAnalyser: () => analyser, destination: {}, resume: vi.fn(), state: 'running' }
    vi.stubGlobal('AudioContext', class { constructor() { return ctx } })
    vi.stubGlobal('requestAnimationFrame', (fn: () => void) => setTimeout(fn, 1) as unknown as number)   // macrotask: lets 'ended' fire
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))
    class FakeAudio { src: string; onended: (() => void) | null = null; onerror: null = null; onpause: null = null; currentTime = 0; duration = 1
      constructor(src: string) { this.src = src } play() { setTimeout(() => this.onended?.(), 30); return Promise.resolve() } pause() {} }
    vi.stubGlobal('Audio', FakeAudio)
    vi.stubGlobal('URL', { createObjectURL: () => 'blob:x', revokeObjectURL: vi.fn() })
    const p = audioPlayer(async () => new Blob(['x']), l => levels.push(l))
    await p.play('/clip.wav')
    expect(levels.length).toBeGreaterThan(0)
    expect(Math.max(...levels)).toBeGreaterThan(0.2)          // 40/128 ≈ 0.31 amplitude
    expect(levels.at(-1)).toBe(0)                              // reset when done
    vi.unstubAllGlobals()
  })
})

// SpeechQueue — orders voice.speech clips per run and plays them back to back.
// Pure TS: playback is injected (Player) so it is unit-testable and swappable.
import type { Event } from '../lib/types'

export interface Player {
  /** Resolves when the clip finished (or was stopped); rejects on playback error. */
  play(url: string): Promise<void>
  stop(): void
}

export interface SpeechState { speaking: boolean; queued: number }

interface Clip { run_id: string; seq: number; url: string; text: string }

export class SpeechQueue {
  private pending = new Map<string, Map<number, Clip>>()   // run_id → seq → clip
  private nextSeq = new Map<string, number>()
  private order: string[] = []                              // run ids in arrival order
  private speaking = false
  private listeners: Array<(s: SpeechState) => void> = []
  private player: Player

  constructor(player: Player) { this.player = player }

  onChange(fn: (s: SpeechState) => void): () => void {
    this.listeners.push(fn)
    return () => { this.listeners = this.listeners.filter(l => l !== fn) }
  }

  state(): SpeechState {
    let queued = 0
    for (const m of this.pending.values()) queued += m.size
    return { speaking: this.speaking, queued }
  }

  handle(e: Event): void {
    if (e.type === 'voice.speech') {
      const p = e.payload as unknown as Clip
      if (!this.pending.has(p.run_id)) { this.pending.set(p.run_id, new Map()); this.order.push(p.run_id) }
      this.pending.get(p.run_id)!.set(p.seq, p)
      if (!this.nextSeq.has(p.run_id)) this.nextSeq.set(p.run_id, 0)
      void this.pump()
    } else if (e.type === 'voice.stopped' || e.type === 'voice.interrupt') {
      this.pending.clear(); this.nextSeq.clear(); this.order = []
      this.player.stop()
      this.emit()
    }
  }

  private takeNext(): Clip | null {
    // Only the *oldest* run may be waiting on a gap; newer runs start fresh.
    for (let i = 0; i < this.order.length; i++) {
      const run = this.order[i]
      const m = this.pending.get(run)
      if (!m) continue
      const want = this.nextSeq.get(run) ?? 0
      const clip = m.get(want)
      if (clip) {
        m.delete(want); this.nextSeq.set(run, want + 1)
        return clip
      }
      if (i === 0 && m.size === 0) { this.pending.delete(run); this.order.shift(); i--; continue }
      // older run has a gap; a newer run supersedes it
      if (i < this.order.length - 1) { this.pending.delete(run); this.order.splice(i, 1); i--; continue }
    }
    return null
  }

  private async pump(): Promise<void> {
    if (this.speaking) return
    let clip = this.takeNext()
    while (clip) {
      this.speaking = true; this.emit()
      try { await this.player.play(clip.url) } catch { /* skip broken clip, keep talking */ }
      clip = this.takeNext()
    }
    this.speaking = false; this.emit()
  }

  private emit() { const s = this.state(); for (const l of this.listeners) l(s) }
}

/** Browser Player on top of HTMLAudioElement. Auth header can't be set on <audio>,
 * so clips are fetched with the bearer and played from a blob URL. */
export function audioPlayer(fetchClip: (url: string) => Promise<Blob>): Player {
  let current: HTMLAudioElement | null = null
  return {
    async play(url) {
      const blob = await fetchClip(url)
      const src = URL.createObjectURL(blob)
      const el = new Audio(src)
      current = el
      try {
        await new Promise<void>((res, rej) => {
          el.onended = () => res()
          el.onerror = () => rej(new Error('audio error'))
          el.onpause = () => { if (el.currentTime < el.duration) res() }  // stopped
          el.play().catch(rej)
        })
      } finally {
        URL.revokeObjectURL(src)
        if (current === el) current = null
      }
    },
    stop() { current?.pause(); current = null },
  }
}

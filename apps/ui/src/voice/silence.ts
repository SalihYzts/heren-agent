// SilenceDetector — decides when a click-to-talk recording should send itself.
// Pure: feed(level 0..1, nowMs) → 'send' | 'timeout' | null. No timers, no audio APIs.

export interface SilenceOptions {
  threshold: number    // level above this counts as speech
  holdMs: number       // silence after speech that triggers 'send'
  minSpeechMs: number  // less than this much speech = a blip, ignore
  maxMs: number        // no speech at all for this long → 'timeout'
}

export class SilenceDetector {
  private opts: SilenceOptions
  private start: number | null = null
  private speechMs = 0
  private lastSample: number | null = null
  private lastSpeech: number | null = null
  private done = false

  constructor(opts: SilenceOptions) { this.opts = opts }

  feed(level: number, now: number): 'send' | 'timeout' | null {
    if (this.done) return null
    if (this.start === null) this.start = now
    const dt = this.lastSample === null ? 0 : Math.max(0, now - this.lastSample)
    this.lastSample = now
    if (level >= this.opts.threshold) {
      this.speechMs += dt
      this.lastSpeech = now
      return null
    }
    if (this.lastSpeech !== null && this.speechMs >= this.opts.minSpeechMs && now - this.lastSpeech >= this.opts.holdMs) {
      this.done = true
      return 'send'
    }
    if (this.lastSpeech === null && now - this.start >= this.opts.maxMs) {
      this.done = true
      return 'timeout'
    }
    return null
  }
}

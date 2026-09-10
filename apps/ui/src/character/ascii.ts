// ASCII animation assets: format + resolution + normalisation. No React here.
//
// An asset pack is plain data (JSON-able) so new art can be dropped in without
// touching code. Keys are "activity.mood", "activity", or "default".
//
// v1: { frames: [...] }                 — inline frames, looped from 0
// v2: { intro?: [...], loop?: [...] }   — names into pack.frames; intro plays once,
//                                         then loop repeats (intro-only holds last frame)

export interface CellSize { cols: number; rows: number }

export interface AsciiAnimation {
  frames?: string[]  // v1: each frame: lines joined by "\n"; whitespace is meaningful
  intro?: string[]   // v2: frame names played once
  loop?: string[]    // v2: frame names repeated forever
  fps?: number       // overrides pack fps
}

export interface AsciiAssetPack {
  cell: CellSize          // fixed box every frame is padded/clipped to
  fps: number             // default frame rate
  frames?: Record<string, string>   // v2 named frames
  animations: Record<string, AsciiAnimation>
}

export interface ResolvedAnimation {
  key: string
  frames: string[]        // normalised to the cell, intro followed by loop
  loopStart: number       // index the cycle returns to after the last frame
  fps: number
  fallback: boolean       // true when no activity-specific art existed
  missing: string[]       // frame names that did not exist in pack.frames
}

const EMPTY_FALLBACK = '[ ? ]'

/** Pick the best animation for (activity, mood): exact → activity → default → built-in. */
export function resolveAnimation(pack: AsciiAssetPack, activity: string, mood: string): ResolvedAnimation {
  const tries: Array<[string, boolean]> = [[`${activity}.${mood}`, false], [activity, false], ['default', true]]
  for (const [key, fb] of tries) {
    const a = pack.animations[key]
    if (!a) continue
    const ex = expand(pack, a)
    if (ex.frames.length > 0) {
      return { key, frames: normalizeFrames(ex.frames, pack.cell), loopStart: ex.loopStart, fps: a.fps ?? pack.fps, fallback: fb, missing: ex.missing }
    }
  }
  return { key: '__builtin', frames: normalizeFrames([EMPTY_FALLBACK], pack.cell), loopStart: 0, fps: 1, fallback: true, missing: [] }
}

function expand(pack: AsciiAssetPack, a: AsciiAnimation): { frames: string[]; loopStart: number; missing: string[] } {
  if (a.frames && a.frames.length > 0) return { frames: a.frames, loopStart: 0, missing: [] }
  const missing: string[] = []
  const pick = (names: string[] | undefined) => (names ?? []).flatMap(n => {
    const f = pack.frames?.[n]
    if (f === undefined) { missing.push(n); return [] }
    return [f]
  })
  const intro = pick(a.intro)
  const loop = pick(a.loop)
  const frames = [...intro, ...loop]
  const loopStart = loop.length > 0 ? intro.length : Math.max(0, frames.length - 1)
  return { frames, loopStart, missing }
}

/** Index of the frame after `i`: intro runs once, then the tail from loopStart cycles. */
export function nextFrameIndex(i: number, length: number, loopStart: number): number {
  if (length <= 1) return 0
  return i + 1 < length ? i + 1 : Math.min(loopStart, length - 1)
}

/** Pad/clip every frame to exactly cell.rows lines of cell.cols chars. */
export function normalizeFrames(frames: string[], cell: CellSize): string[] {
  return frames.map(f => {
    const lines = f.replace(/\r/g, '').split('\n')
    if (lines.length > 0 && lines[lines.length - 1] === '' && lines.length > cell.rows) lines.pop()
    const out: string[] = []
    for (let r = 0; r < cell.rows; r++) {
      const line = (lines[r] ?? '').slice(0, cell.cols)
      out.push(line + ' '.repeat(cell.cols - line.length))
    }
    return out.join('\n')
  })
}

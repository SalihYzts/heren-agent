// ASCII animation assets: format + resolution + normalisation. No React here.
//
// An asset pack is plain data (JSON-able) so new art can be dropped in without
// touching code. Keys are "activity.mood", "activity", or "default".

export interface CellSize { cols: number; rows: number }

export interface AsciiAnimation {
  frames: string[]   // each frame: lines joined by "\n"; whitespace is meaningful
  fps?: number       // overrides pack fps
}

export interface AsciiAssetPack {
  cell: CellSize          // fixed box every frame is padded/clipped to
  fps: number             // default frame rate
  animations: Record<string, AsciiAnimation>
}

export interface ResolvedAnimation {
  key: string
  frames: string[]        // normalised to the cell
  fps: number
  fallback: boolean       // true when no activity-specific art existed
}

const EMPTY_FALLBACK = '[ ? ]'

/** Pick the best animation for (activity, mood): exact → activity → default → built-in. */
export function resolveAnimation(pack: AsciiAssetPack, activity: string, mood: string): ResolvedAnimation {
  const tries: Array<[string, boolean]> = [[`${activity}.${mood}`, false], [activity, false], ['default', true]]
  for (const [key, fb] of tries) {
    const a = pack.animations[key]
    if (a && a.frames.length > 0) {
      return { key, frames: normalizeFrames(a.frames, pack.cell), fps: a.fps ?? pack.fps, fallback: fb }
    }
  }
  return { key: '__builtin', frames: normalizeFrames([EMPTY_FALLBACK], pack.cell), fps: 1, fallback: true }
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

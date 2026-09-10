// Runtime pack loading: art ships as static JSON (public/character/*.json) so
// artists can replace it without a rebuild. Anything wrong → built-in pack + reason.
import type { AsciiAssetPack } from './ascii'
import { defaultPack } from './defaultPack'

export interface LoadedPack { pack: AsciiAssetPack; source: string; error?: string }

export function validatePack(p: unknown): string | null {
  if (!p || typeof p !== 'object') return 'pack is not an object'
  const o = p as Record<string, unknown>
  const cell = o.cell as { cols?: unknown; rows?: unknown } | undefined
  if (!cell || typeof cell.cols !== 'number' || typeof cell.rows !== 'number' || !Number.isInteger(cell.cols) || !Number.isInteger(cell.rows) || cell.cols < 1 || cell.rows < 1) return 'cell must have finite integer cols/rows ≥ 1'
  if (typeof o.fps !== 'number' || !Number.isFinite(o.fps) || o.fps <= 0) return 'fps must be finite and > 0'
  if (o.frames !== undefined) {
    if (typeof o.frames !== 'object' || o.frames === null || Array.isArray(o.frames)) return 'frames must be an object'
    for (const [k, v] of Object.entries(o.frames as Record<string, unknown>)) if (typeof v !== 'string') return `frame ${k} is not a string`
  }
  const anims = o.animations as Record<string, unknown> | undefined
  if (!anims || typeof anims !== 'object' || Array.isArray(anims) || Object.keys(anims).length === 0) return 'animations must be a non-empty object'
  for (const [key, value] of Object.entries(anims)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return `animation ${key} must be an object`
    const animation = value as Record<string, unknown>
    if (animation.fps !== undefined && (typeof animation.fps !== 'number' || !Number.isFinite(animation.fps) || animation.fps <= 0)) return `animation ${key}.fps must be finite and > 0`
    for (const field of ['frames', 'intro', 'loop']) {
      const frames = animation[field]
      if (frames !== undefined && (!Array.isArray(frames) || frames.some(frame => typeof frame !== 'string'))) return `animation ${key}.${field} must be a string array`
    }
  }
  return null
}

export async function loadPack(url: string, fetchFn: typeof fetch = fetch): Promise<LoadedPack> {
  try {
    const r = await fetchFn(url, { cache: 'no-cache' })
    if (!r.ok) return { pack: defaultPack, source: 'builtin', error: `HTTP ${r.status}` }
    const json = await r.json()
    const why = validatePack(json)
    if (why) return { pack: defaultPack, source: 'builtin', error: why }
    return { pack: json as AsciiAssetPack, source: url }
  } catch (e) {
    return { pack: defaultPack, source: 'builtin', error: (e as Error).message }
  }
}

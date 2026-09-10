import { describe, expect, it, vi } from 'vitest'
import { loadPack, validatePack } from './loadPack'
import { defaultPack } from './defaultPack'
import { resolveAnimation } from './ascii'

const good = { cell: { cols: 2, rows: 1 }, fps: 4, frames: { a: 'AA' }, animations: { idle: { loop: ['a'] }, default: { loop: ['a'] } } }

describe('validatePack', () => {
  it('accepts a well-formed v2 pack', () => {
    expect(validatePack(good)).toBeNull()
  })
  it.each([null, [], 'a', 1, true].map(entry => ({ entry })))('rejects malformed animation entry $entry', ({ entry }) => {
    expect(validatePack({ ...good, animations: { idle: entry } })).toMatch(/animation/)
  })
  it('rejects arrays used as animation or frame dictionaries', () => {
    expect(validatePack({ ...good, animations: [{ loop: ['a'] }] })).toMatch(/animations/)
    expect(validatePack({ ...good, frames: ['AA'] })).toMatch(/frames/)
  })
  it.each(['frames', 'intro', 'loop'])('requires animation %s to be a string array', field => {
    for (const value of [null, 'a', {}, 1, [null], [1], ['a', {}]]) {
      expect(validatePack({ ...good, animations: { idle: { [field]: value } } })).toMatch(new RegExp(field))
    }
  })
  it('rejects garbage with a reason', () => {
    expect(validatePack(null)).toMatch(/object/)
    expect(validatePack({ ...good, cell: { cols: 0, rows: 1 } })).toMatch(/cell/)
    expect(validatePack({ ...good, animations: {} })).toMatch(/animations/)
    expect(validatePack({ ...good, frames: { a: 5 } })).toMatch(/frame/)
  })
  it.each(['cols', 'rows'])('requires cell %s to be a positive finite integer', field => {
    for (const value of [NaN, Infinity, -Infinity, 1.5, 0, -1, '2', null]) {
      expect(validatePack({ ...good, cell: { ...good.cell, [field]: value } })).toMatch(/cell/)
    }
  })
  it('requires pack and animation fps to be finite positive numbers', () => {
    for (const fps of [NaN, Infinity, -Infinity, 0, -1, '4', null]) {
      expect(validatePack({ ...good, fps })).toMatch(/fps/)
      expect(validatePack({ ...good, animations: { idle: { loop: ['a'], fps } } })).toMatch(/fps/)
    }
    expect(validatePack({ ...good, fps: 0.5, animations: { idle: { frames: ['AA'], fps: 1.5 } } })).toBeNull()
  })
})

describe('loadPack', () => {
  it.each([null, { loop: 'a' }, { intro: [1] }, { frames: [null] }, { fps: Infinity }])('falls back before resolving malformed fetched animations %j', entry => {
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => ({ ...good, animations: { idle: entry } }) })) as unknown as typeof fetch
    return loadPack('/bad.json', fetchFn).then(result => {
      expect(result.pack).toBe(defaultPack)
      expect(result.source).toBe('builtin')
      expect(result.error).toMatch(/animation/)
      expect(() => resolveAnimation(result.pack, 'idle', 'neutral')).not.toThrow()
    })
  })
  it('preserves missing reference diagnostics without rejecting the fetched pack', async () => {
    const pack = { ...good, animations: { idle: { intro: ['missing'], loop: ['a'] } } }
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => pack })) as unknown as typeof fetch
    const result = await loadPack('/partial.json', fetchFn)
    expect(result.source).toBe('/partial.json')
    expect(result.error).toBeUndefined()
    expect(resolveAnimation(result.pack, 'idle', 'neutral')).toMatchObject({ frames: ['AA'], missing: ['missing'], fallback: false })
  })
  it('preserves default and built-in fallback for empty or missing-only animations', async () => {
    for (const idle of [{}, { frames: [], intro: [], loop: [] }, { loop: ['missing'] }]) {
      const pack = { ...good, animations: { idle, default: { frames: ['OK'] } } }
      const fetchFn = vi.fn(async () => ({ ok: true, json: async () => pack })) as unknown as typeof fetch
      const result = await loadPack('/partial.json', fetchFn)
      expect(result.source).toBe('/partial.json')
      expect(resolveAnimation(result.pack, 'idle', 'neutral')).toMatchObject({ key: 'default', frames: ['OK'], fallback: true })
      const missingOnly = { ...good, frames: undefined, animations: { idle } }
      expect(validatePack(missingOnly)).toBeNull()
      expect(resolveAnimation(missingOnly, 'idle', 'neutral')).toMatchObject({ key: '__builtin', fallback: true })
    }
  })
  it('fetches the pack from the given url', async () => {
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => good })) as unknown as typeof fetch
    const r = await loadPack('/character/heren.json', fetchFn)
    expect(r.pack).toEqual(good)
    expect(r.source).toBe('/character/heren.json')
  })
  it('falls back to the built-in pack on 404, network error or invalid content', async () => {
    const notFound = vi.fn(async () => ({ ok: false, status: 404 })) as unknown as typeof fetch
    expect((await loadPack('/x.json', notFound)).pack).toBe(defaultPack)
    const boom = vi.fn(async () => { throw new Error('net') }) as unknown as typeof fetch
    const r = await loadPack('/x.json', boom)
    expect(r.pack).toBe(defaultPack)
    expect(r.source).toBe('builtin')
    expect(r.error).toMatch(/net/)
    const bad = vi.fn(async () => ({ ok: true, json: async () => ({ nope: 1 }) })) as unknown as typeof fetch
    expect((await loadPack('/x.json', bad)).error).toMatch(/cell/)
  })
})

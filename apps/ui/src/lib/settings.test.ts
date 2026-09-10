import { beforeEach, describe, expect, it } from 'vitest'
import { THEMES, applyTheme, loadSettings, saveSettings, type Settings } from './settings'

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute('data-theme') })

describe('settings', () => {
  it('defaults to the nothing theme and the shipped heren look', () => {
    expect(loadSettings()).toEqual({ theme: 'nothing', look: 'heren', server: null })
  })
  it('round-trips through localStorage and ignores unknown values', () => {
    saveSettings({ theme: 'paper', look: 'heren', server: 'dev-1' })
    expect(loadSettings()).toEqual({ theme: 'paper', look: 'heren', server: 'dev-1' })
    localStorage.setItem('heren.settings.v1', JSON.stringify({ theme: 'neon-nope', look: 42 }))
    expect(loadSettings()).toEqual({ theme: 'nothing', look: 'heren', server: null })
    localStorage.setItem('heren.settings.v1', '{not json')
    expect(loadSettings()).toEqual({ theme: 'nothing', look: 'heren', server: null })
  })
  it('applies the theme to the document so CSS variables can switch', () => {
    applyTheme('paper')
    expect(document.documentElement.dataset.theme).toBe('paper')
    applyTheme('nothing')
    expect(document.documentElement.dataset.theme).toBe('nothing')
  })
  it('every theme has a Turkish label and a distinct id', () => {
    const ids = THEMES.map(t => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const t of THEMES) expect(t.label.length).toBeGreaterThan(2)
  })
  it('look ids map to a character pack url', () => {
    const s: Settings = { theme: 'nothing', look: 'heren', server: null }
    expect(s.look).toBe('heren')
  })
})

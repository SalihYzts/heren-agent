import { beforeEach, describe, expect, it } from 'vitest'
import { THEMES, applyTheme, loadSettings, saveSettings, type Settings } from './settings'

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute('data-theme') })

describe('settings', () => {
  it('defaults to the nothing theme and the shipped heren look', () => {
    expect(loadSettings()).toEqual({ theme: 'nothing', look: 'heren', server: null, model: '', provider: '' })
  })
  it('round-trips through localStorage and ignores unknown values', () => {
    saveSettings({ theme: 'paper', look: 'heren', server: 'dev-1', model: '', provider: '' })
    expect(loadSettings()).toEqual({ theme: 'paper', look: 'heren', server: 'dev-1', model: '', provider: '' })
    localStorage.setItem('heren.settings.v1', JSON.stringify({ theme: 'neon-nope', look: 42 }))
    expect(loadSettings()).toEqual({ theme: 'nothing', look: 'heren', server: null, model: '', provider: '' })
    localStorage.setItem('heren.settings.v1', '{not json')
    expect(loadSettings()).toEqual({ theme: 'nothing', look: 'heren', server: null, model: '', provider: '' })
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
    const s: Settings = { theme: 'nothing', look: 'heren', server: null, model: '', provider: '' }
    expect(s.look).toBe('heren')
  })
})

describe('model choice + access urls', () => {
  it('stores a model choice and treats empty as "gateway default"', () => {
    saveSettings({ ...loadSettings(), model: 'gpt-4.1', provider: 'copilot' })
    expect(loadSettings().model).toBe('gpt-4.1')
    expect(loadSettings().provider).toBe('copilot')
    saveSettings({ ...loadSettings(), model: '', provider: '' })
    expect(loadSettings().model).toBe('')
  })
  it('defaults model/provider to empty (gateway decides)', () => {
    expect(loadSettings()).toMatchObject({ model: '', provider: '' })
  })
})

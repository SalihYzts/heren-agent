import { beforeEach, describe, expect, it } from 'vitest'
import { clearSession, loadSession, saveSession, REMEMBER_MS } from './session'

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })

describe('session key storage', () => {
  it('without "remember" the key lives only for the tab (sessionStorage)', () => {
    saveSession('k1', false, 1000)
    expect(loadSession(1000)).toBe('k1')
    expect(sessionStorage.getItem('heren.api_key')).toBe('k1')
    expect(localStorage.getItem('heren.session.v1')).toBeNull()
  })

  it('with "remember" the key survives in localStorage until it expires', () => {
    saveSession('k2', true, 1000)
    sessionStorage.clear()                                    // "tab closed"
    expect(loadSession(1000 + REMEMBER_MS - 1)).toBe('k2')
    sessionStorage.clear()                                    // tab closed again, later
    expect(loadSession(1000 + 2 * REMEMBER_MS + 1)).toBeNull()   // past the (slid) expiry → gone
    expect(localStorage.getItem('heren.session.v1')).toBeNull()
  })

  it('loading a remembered key slides the expiry forward', () => {
    saveSession('k3', true, 0)
    sessionStorage.clear()
    loadSession(REMEMBER_MS / 2)
    sessionStorage.clear()
    expect(loadSession(REMEMBER_MS + 10)).toBe('k3')         // would have expired without the slide
  })

  it('logout clears both stores; garbage in localStorage is ignored', () => {
    saveSession('k4', true, 0)
    clearSession()
    expect(loadSession(1)).toBeNull()
    localStorage.setItem('heren.session.v1', '{broken')
    expect(loadSession(1)).toBeNull()
  })
})

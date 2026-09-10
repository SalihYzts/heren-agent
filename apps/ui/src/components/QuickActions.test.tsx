import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { QuickActions } from './QuickActions'
import type { Device } from '../lib/types'
const device: Device = { device_id: 'pc', name: 'Sunucu', status: 'online', capabilities: ['get_status', 'restart_service', 'shutdown'], platform: 'linux', public_key: '', last_seen: null }
beforeEach(() => localStorage.clear())
it('creates, edits, restores and deletes a shortcut without executing during editing', () => {
  const run = vi.fn()
  const { unmount } = render(<QuickActions devices={[device]} onAction={run} />)
  fireEvent.click(screen.getByRole('button', { name: 'Düğme ekle' }))
  fireEvent.change(screen.getByLabelText('Düğme adı'), { target: { value: 'Durumum' } })
  fireEvent.change(screen.getByLabelText('Cihaz'), { target: { value: 'pc' } })
  fireEvent.change(screen.getByLabelText('İşlem'), { target: { value: 'get_status' } })
  fireEvent.click(screen.getByRole('button', { name: 'Kaydet' }))
  expect(run).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: /Durumum çalıştır/ }))
  expect(run).toHaveBeenCalledWith('pc', 'get_status', {})
  fireEvent.click(screen.getByRole('button', { name: 'Durumum düzenle' }))
  fireEvent.change(screen.getByLabelText('Düğme adı'), { target: { value: 'Yeni durum' } })
  fireEvent.click(screen.getByRole('button', { name: 'Kaydet' }))
  unmount()
  render(<QuickActions devices={[device]} onAction={run} />)
  expect(screen.getByRole('button', { name: /Yeni durum çalıştır/ })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Yeni durum düzenle' }))
  fireEvent.click(screen.getByRole('button', { name: 'Düğmeyi sil' }))
  expect(screen.queryByRole('button', { name: /Yeni durum çalıştır/ })).toBeNull()
})
it('keeps offline actions disabled and explains high-risk approval', () => {
  localStorage.setItem('heren.shortcuts.v1', JSON.stringify([{ id: 'x', name: 'Kapat', deviceId: 'pc', action: 'shutdown', value: '' }]))
  render(<QuickActions devices={[{ ...device, status: 'offline' }]} onAction={vi.fn()} />)
  expect(screen.getByRole('button', { name: /Kapat çalıştır/ })).toBeDisabled()
  expect(screen.getByText(/Onay gerekir/)).toBeVisible()
})

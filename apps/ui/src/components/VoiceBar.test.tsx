import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { VoiceBar } from './VoiceBar'

const voice = { tts: 'piper', stt: 'faster_whisper', language: 'tr', transcript: null, error: null }

describe('VoiceBar', () => {
  it('invites the user in the quiet state and keeps provider names behind details', () => {
    render(<VoiceBar voice={voice} speaking={false} queued={0} recorder={null} onStop={() => {}} />)
    expect(screen.getByTestId('voice-status')).toHaveTextContent('Heren’e dokun, konuşalım')
    expect(screen.getByText(/piper/)).toBeInTheDocument()
    expect(screen.getByText(/faster_whisper/)).toBeInTheDocument()
  })

  it('gives clear listening feedback with a live level meter while recording', () => {
    const recorder = { start: vi.fn(), stop: vi.fn(), active: true, level: 0.6 }
    render(<VoiceBar voice={voice} speaking={false} queued={0} recorder={recorder} onStop={() => {}} />)
    const status = screen.getByTestId('voice-status')
    expect(status).toHaveTextContent('Seni dinliyorum')
    expect(status).toHaveAttribute('data-listening', 'true')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByRole('meter', { name: 'Mikrofon ses seviyesi' })).toHaveValue(0.6)
  })

  it('lets the user cancel while the permission prompt is pending and shows recorder errors', () => {
    const recorder = { start: vi.fn(), stop: vi.fn(), active: false, pending: true, error: 'Mikrofon izni verilmedi.' }
    render(<VoiceBar voice={voice} speaking={false} queued={0} recorder={recorder} onStop={() => {}} />)
    expect(screen.getByTestId('voice-status')).toHaveTextContent('Mikrofon izni bekleniyor')
    fireEvent.click(screen.getByRole('button', { name: 'İptal et' }))
    expect(recorder.stop).toHaveBeenCalledOnce()
    expect(screen.getByRole('alert')).toHaveTextContent('Mikrofon izni verilmedi.')
  })

  it('shows speaking with queue depth and a stop button that calls back', () => {
    const onStop = vi.fn()
    render(<VoiceBar voice={voice} speaking={true} queued={2} recorder={null} onStop={onStop} />)
    expect(screen.getByTestId('voice-status')).toHaveTextContent('konuşuyor · +2')
    fireEvent.click(screen.getByRole('button', { name: /durdur/i }))
    expect(onStop).toHaveBeenCalled()
  })

  it('disables the mic when there is no recorder and says why', () => {
    render(<VoiceBar voice={voice} speaking={false} queued={0} recorder={null} onStop={() => {}} />)
    const mic = screen.getByRole('button', { name: /konuş/i })
    expect(mic).toBeDisabled()
    expect(mic).toHaveAttribute('title', expect.stringMatching(/mikrofon/i))
  })

  it('starts only on click and sends only on a second click', () => {
    const recorder = { start: vi.fn(), stop: vi.fn(), active: false }
    const { rerender } = render(<VoiceBar voice={voice} speaking={false} queued={0} recorder={recorder} onStop={() => {}} />)
    const mic = screen.getByRole('button', { name: 'Konuşmaya başla' })
    fireEvent.pointerDown(mic)
    expect(recorder.start).not.toHaveBeenCalled()
    fireEvent.click(mic)
    expect(recorder.start).toHaveBeenCalledOnce()
    rerender(<VoiceBar voice={voice} speaking={false} queued={0} recorder={{ ...recorder, active: true }} onStop={() => {}} />)
    const send = screen.getByRole('button', { name: 'Bitir ve gönder' })
    expect(send).toHaveAttribute('aria-pressed', 'true')
    fireEvent.pointerLeave(send)
    expect(recorder.stop).not.toHaveBeenCalled()
    fireEvent.click(send)
    expect(recorder.stop).toHaveBeenCalledOnce()
  })

  it('shows the last transcript and errors', () => {
    render(<VoiceBar voice={{ ...voice, transcript: 'sunucu nasıl', error: 'engine died' }} speaking={false} queued={0} recorder={null} onStop={() => {}} />)
    expect(screen.getByText(/sunucu nasıl/)).toBeInTheDocument()
    expect(screen.getByText(/engine died/)).toBeInTheDocument()
  })

  it('stt=none hides the mic entirely', () => {
    render(<VoiceBar voice={{ ...voice, stt: 'none' }} speaking={false} queued={0} recorder={null} onStop={() => {}} />)
    expect(screen.queryByRole('button', { name: /konuş/i })).toBeNull()
  })
})

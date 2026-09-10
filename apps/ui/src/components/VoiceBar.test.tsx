import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { VoiceBar } from './VoiceBar'

const voice = { tts: 'piper', stt: 'faster_whisper', language: 'tr', transcript: null, error: null }

describe('VoiceBar', () => {
  it('shows providers and a quiet state', () => {
    render(<VoiceBar voice={voice} speaking={false} queued={0} recorder={null} onStop={() => {}} />)
    expect(screen.getByTestId('voice-status')).toHaveTextContent('sessiz')
    expect(screen.getByText(/piper/)).toBeInTheDocument()
    expect(screen.getByText(/faster_whisper/)).toBeInTheDocument()
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

  it('push-to-talk: press starts, release stops the recorder', () => {
    const recorder = { start: vi.fn(), stop: vi.fn(), active: false }
    render(<VoiceBar voice={voice} speaking={false} queued={0} recorder={recorder} onStop={() => {}} />)
    const mic = screen.getByRole('button', { name: /konuş/i })
    fireEvent.pointerDown(mic)
    expect(recorder.start).toHaveBeenCalled()
    fireEvent.pointerUp(mic)
    expect(recorder.stop).toHaveBeenCalled()
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

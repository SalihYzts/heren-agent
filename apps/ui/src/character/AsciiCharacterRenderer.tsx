import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { nextFrameIndex, resolveAnimation, type AsciiAssetPack, type CellSize } from './ascii'

interface Props {
  pack: AsciiAssetPack
  activity: string
  mood: string
  energy?: number          // 0..1; low energy slows playback (presentation only)
  fit?: boolean            // scale font so the whole cell fits the parent box (default true)
  className?: string
  onClick?: () => void
}

const CHAR_ASPECT = 0.6    // monospace glyph width / font-size (DejaVu/JetBrains ≈ 0.6)
const LINE_HEIGHT = 1.0    // tight rows: ASCII-from-image art assumes square-ish cells

/** Largest font-size (px) at which cols×rows fits in w×h. 0 when the box has no size. */
export function fitFontSize(cell: CellSize, w: number, h: number, aspect = CHAR_ASPECT, lineHeight = LINE_HEIGHT): number {
  if (w <= 0 || h <= 0 || cell.cols <= 0 || cell.rows <= 0) return 0
  return Math.min(w / (cell.cols * aspect), h / (cell.rows * lineHeight))
}

/** Playback speed factor from energy: 1.0 at full energy, 0.5 when exhausted. */
export function speedFor(energy: number | undefined): number {
  if (energy === undefined) return 1
  const e = Math.max(0, Math.min(1, energy))
  return e < 0.35 ? 0.5 : 1
}

/**
 * Draws one ASCII frame in a <pre> of fixed size (cols×rows) so layout never
 * jumps between frames or states. Intro frames play once, then the loop cycles.
 * Changing activity/mood restarts at frame 0. Font is scaled to fit the parent.
 */
export function AsciiCharacterRenderer({ pack, activity, mood, energy, fit = true, className, onClick }: Props) {
  const anim = useMemo(() => resolveAnimation(pack, activity, mood), [pack, activity, mood])
  const [i, setI] = useState(0)
  const speed = speedFor(energy)

  useEffect(() => {
    setI(0)
    if (anim.frames.length < 2 || anim.fps <= 0) return
    const t = setInterval(() => setI(x => nextFrameIndex(x, anim.frames.length, anim.loopStart)), 1000 / (anim.fps * speed))
    return () => clearInterval(t)
  }, [anim, speed])

  // ---- fit to the parent box -------------------------------------------
  const ref = useRef<HTMLPreElement>(null)
  const [fontPx, setFontPx] = useState<number | null>(null)
  useLayoutEffect(() => {
    if (!fit || typeof ResizeObserver === 'undefined') return
    const el = ref.current?.parentElement
    if (!el) return
    const measure = () => {
      const pre = ref.current!
      // Measure at 16px: tiny font metrics round differently for ch and glyphs.
      setFontPx(16 * Math.min(el.clientWidth / pre.scrollWidth, el.clientHeight / pre.scrollHeight))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [fit, pack.cell])

  const frame = anim.frames[i % anim.frames.length] ?? anim.frames[0]
  const phase = i < anim.loopStart ? 'intro' : 'loop'
  const cls = [className, `is-${activity}`, `mood-${mood}`, anim.fallback ? 'is-fallback' : ''].filter(Boolean).join(' ')
  return (
    <pre
      ref={ref}
      data-testid="ascii-frame"
      data-activity={activity}
      data-mood={mood}
      data-anim={anim.key}
      data-phase={phase}
      data-frame={i}
      data-fallback={anim.fallback ? 'true' : undefined}
      className={cls}
      onClick={onClick}
      style={{
        margin: 0, fontFamily: 'var(--mono, monospace)', whiteSpace: 'pre',
        width: 'max-content', minWidth: `${pack.cell.cols}ch`, height: `${pack.cell.rows}lh`,
        lineHeight: LINE_HEIGHT, overflow: 'hidden',
        fontSize: '16px',
        ...(fit && fontPx ? {
          position: 'absolute', left: '50%', top: '50%',
          transform: `translate(-50%, -50%) scale(${fontPx / 16})`,
        } : {}),
      }}
    >{frame}</pre>
  )
}

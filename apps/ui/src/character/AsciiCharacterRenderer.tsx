import { useEffect, useMemo, useState } from 'react'
import { resolveAnimation, type AsciiAssetPack } from './ascii'

interface Props {
  pack: AsciiAssetPack
  activity: string
  mood: string
  className?: string
  onClick?: () => void
}

/**
 * Draws one ASCII frame in a <pre> of fixed size (cols×rows) so layout never
 * jumps between frames or states. Frame index is a timer driven by the
 * animation's fps; changing activity/mood restarts at frame 0.
 */
export function AsciiCharacterRenderer({ pack, activity, mood, className, onClick }: Props) {
  const anim = useMemo(() => resolveAnimation(pack, activity, mood), [pack, activity, mood])
  const [i, setI] = useState(0)

  useEffect(() => {
    setI(0)
    if (anim.frames.length < 2 || anim.fps <= 0) return
    const t = setInterval(() => setI(x => (x + 1) % anim.frames.length), 1000 / anim.fps)
    return () => clearInterval(t)
  }, [anim])

  const frame = anim.frames[i % anim.frames.length] ?? anim.frames[0]
  return (
    <pre
      data-testid="ascii-frame"
      data-activity={activity}
      data-mood={mood}
      data-anim={anim.key}
      data-fallback={anim.fallback ? 'true' : undefined}
      className={className}
      onClick={onClick}
      style={{
        margin: 0, fontFamily: 'var(--mono, monospace)', whiteSpace: 'pre',
        width: `${pack.cell.cols}ch`, height: `${pack.cell.rows}lh`,
        lineHeight: 1.2, overflow: 'hidden',
      }}
    >{frame}</pre>
  )
}

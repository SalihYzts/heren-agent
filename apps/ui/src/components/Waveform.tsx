// Waveform — a music-player style level wave. Pure SVG, no canvas, no deps.
// tone="user": drawn IN FRONT of the character, green, while the mic is open.
// tone="heren": drawn BEHIND the character in the theme's foreground colour while Heren talks.

export function wavePath(levels: number[], w: number, h: number): string {
  if (levels.length === 0) return ''
  const mid = h / 2
  const n = levels.length
  const x = (i: number) => n === 1 ? w / 2 : (i / (n - 1)) * w
  const clamp = (v: number) => Math.max(0, Math.min(1, v))
  const top = levels.map((l, i) => `${x(i)},${mid - clamp(l) * mid}`)
  const bottom = levels.map((l, i) => `${x(i)},${mid + clamp(l) * mid}`).reverse()
  return `M${top[0]} L${top.slice(1).join(' L')} L${bottom.join(' L')} Z`
}

interface Props { levels: number[]; active: boolean; tone: 'user' | 'heren'; className?: string }

export function Waveform({ levels, active, tone, className }: Props) {
  const W = 300, H = 100
  return (
    <svg className={`wave ${className ?? ''}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
      data-tone={tone} data-active={active ? 'true' : 'false'} aria-hidden>
      <line x1="0" y1={H / 2} x2={W} y2={H / 2} className="wave-axis" />
      {active && <path d={wavePath(levels, W, H)} className="wave-fill" />}
    </svg>
  )
}

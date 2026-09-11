// Sparkline — a tiny line chart. Pure SVG, values scaled into a fixed box, newest at the right.

export function sparkPath(values: number[], w: number, h: number, max?: number): string {
  if (values.length < 2) return ''
  const lo = 0
  // no explicit max → leave headroom so a flat series is not glued to the top edge
  const hi = max ?? Math.max(...values) * 2
  const span = hi - lo || 1
  const x = (i: number) => (i / (values.length - 1)) * w
  const y = (v: number) => h - ((Math.min(Math.max(v, lo), hi) - lo) / span) * h
  return values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(v)}`).join(' ')
}

interface Props { values: number[]; max?: number; label?: string; className?: string }

export function Sparkline({ values, max, label, className }: Props) {
  const W = 120, H = 24
  return (
    <svg className={`spark ${className ?? ''}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
      role="img" aria-label={label ?? 'geçmiş'} data-points={values.length}>
      <path d={sparkPath(values, W, H, max)} className="spark-line" />
    </svg>
  )
}

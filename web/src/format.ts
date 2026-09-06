/* One place for the way this workspace writes numbers: mono, tabular, unit spelled out
   in the smaller face beside the figure. Wall-clock durations read as minutes only once
   they stop being legible in seconds. */
export function seconds(value: number | null | undefined) {
  if (value === undefined || value === null || !isFinite(value)) return '—'
  if (value < 90) return `${Math.round(value)} s`
  const minutes = Math.floor(value / 60)
  const rest = Math.round(value % 60)
  return rest ? `${minutes} m ${rest} s` : `${minutes} m`
}

export function stopwatch(value: number | null | undefined) {
  if (value === undefined || value === null || !isFinite(value)) return '––:––'
  const total = Math.max(0, Math.round(value))
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

export function millis(value: number | null | undefined) {
  if (value === undefined || value === null) return '—'
  return value < 10 ? value.toFixed(2) : Math.round(value).toLocaleString()
}

export function percent(value: number | null | undefined, digits = 2) {
  if (value === undefined || value === null) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function count(value: number | null | undefined) {
  if (value === undefined || value === null) return '—'
  return Math.round(value).toLocaleString()
}

export function clock(value: string | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  return isNaN(parsed.valueOf()) ? '—' : parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/* Error rate is the one figure with an unambiguous direction, so it is the only one
   allowed to carry colour. Latency and throughput mean nothing without the target's own
   objectives, so they stay neutral and a healthy run reads calm rather than alarmed. */
export function errorTone(rate: number | null | undefined) {
  if (rate === undefined || rate === null) return ''
  return rate === 0 ? 'good' : rate <= 0.01 ? 'warn' : 'bad'
}

import type { Intent, Reading as ReadingModel } from '../types'
import { millis, percent, seconds } from '../format'

/* What the requirement was understood to mean, printed as an argument rather than as
   JSON. Each line is one phrase somebody wrote next to the operation it resolved to and
   how sure that resolution is, so a wrong reading is visible before any traffic is sent
   rather than afterwards in a metric nobody expected. */
function Meter({ value }: { value: number }) {
  return <div className="meter" role="presentation"><i style={{ width: `${Math.max(3, Math.min(100, value * 100))}%` }} /></div>
}

function Cell({ label, value, unit, accent, kind }: { label: string; value: string; unit?: string; accent?: boolean; kind?: boolean }) {
  return <div className={`spec-cell${accent ? ' accent' : ''}${kind ? ' spec-kind' : ''}`}>
    <b>{value}{unit && <i>{unit}</i>}</b><span>{label}</span>
  </div>
}

export function Reading({ reading, intent, plannedSeconds, peak }: { reading: ReadingModel; intent: Intent; plannedSeconds?: number; peak?: string }) {
  const load = peak ?? (intent.target_rps ? `${intent.target_rps} rps` : `${intent.max_concurrency ?? intent.target_concurrency ?? 0} vu`)
  const [loadValue, loadUnit] = load.split(' ')
  const gaps: Array<[string, string, string]> = []
  for (const phrase of reading.unrecognized_phrases) gaps.push(['unread', phrase, 'unread'])
  for (const ambiguity of intent.ambiguities) gaps.push(['assumed', ambiguity, 'note'])
  for (const note of reading.notes) gaps.push(['note', note, 'note'])
  if (reading.generated_inputs?.length) gaps.push(['generated', `Values invented for ${reading.generated_inputs.join(', ')} because the requirement named them without giving them.`, 'note'])
  if (reading.journey_repairs?.length) gaps.push(['repaired', `The model wrote variables nothing produces; these fields were regenerated from their schemas: ${reading.journey_repairs.join(', ')}.`, 'mint'])
  if (reading.journey_error) gaps.push(['rejected', `${reading.journey_error} The deterministic sequence is executing instead.`, 'unread'])
  if (reading.provider_error) gaps.push(['provider', `${reading.provider_error} The deterministic reading stands on its own.`, 'note'])

  return <div className="reading">
    <div className="spec">
      <Cell label="test type" value={intent.test_type.toLowerCase()} kind />
      <Cell label={intent.target_rps ? 'arrival rate' : 'peak concurrency'} value={loadValue} unit={loadUnit} />
      <Cell label="planned duration" value={seconds(plannedSeconds ?? intent.duration_seconds)} />
      {intent.slos.latency_p95_ms != null && <Cell label="p95 objective" value={millis(intent.slos.latency_p95_ms)} unit="ms" accent />}
      {intent.slos.error_rate != null && <Cell label="error budget" value={percent(intent.slos.error_rate)} accent />}
      {intent.slos.throughput_rps != null && <Cell label="throughput floor" value={`${intent.slos.throughput_rps}`} unit="rps" accent />}
      <div className="spec-conf">
        <Meter value={intent.confidence} />
        <span className="m">{Math.round(intent.confidence * 100)} / 100 · read by {reading.source === 'provider' ? 'model + patterns' : 'patterns'}</span>
      </div>
    </div>

    {reading.steps.length > 0 && <div className="matches">
      {reading.steps.map((step, index) => <div className={step.origin === 'provider' ? 'match provider' : 'match'} key={`${step.operation_id}-${index}`}>
        <div className="match-index">{String(index + 1).padStart(2, '0')}</div>
        <div className="match-phrase"><em>“{step.phrase}”</em></div>
        <div className="match-arrow">→</div>
        <div className="match-op"><b><i>{step.method}</i>{step.operation_id}</b><span>{step.path}{step.reasons.length ? ` · ${step.reasons.join(', ')}` : ''}</span></div>
        <div className="match-conf"><b>{Math.round(step.confidence * 100)}</b><Meter value={step.confidence} /></div>
      </div>)}
    </div>}

    {gaps.length > 0 && <div className="gaps">
      {gaps.map(([label, text, tone], index) => <p className={`gap${tone === 'unread' ? '' : ' ' + tone}`} key={`${label}-${index}`}><b>{label}</b><span>{text}</span></p>)}
    </div>}
  </div>
}

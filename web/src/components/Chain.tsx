import type { Journey } from '../types'

/* A journey is only worth anything if the handoffs are right, so the wiring is what this
   prints: each step as a disc on a rule, with the variables it extracts and the ones it
   consumes named on the step itself. A chain missing a binding is visible at a glance. */
export function Chain({ journeys, activeIndex }: { journeys: Journey[]; activeIndex?: number }) {
  const steps = journeys.flatMap((journey) => journey.steps.map((step) => ({ ...step, journey: journey.name })))
  return <div className="chain">
    {steps.map((step, index) => {
      const consumed = Object.entries(step.inputs ?? {}).filter(([, value]) => typeof value === 'string' && value.includes('${'))
      const produced = Object.keys(step.extract ?? {})
      const state = activeIndex === undefined ? '' : index < activeIndex ? ' done' : index === activeIndex ? ' now' : ''
      return <div className={`chain-step${state}`} key={`${step.operation_id}-${index}`}>
        <div className="chain-disc">{String(index + 1).padStart(2, '0')}</div>
        <div className="chain-op">{step.operation_id}</div>
        <div className="chain-detail">
          {consumed.map(([key, value]) => <span className="in" key={key}>uses <b>{String(value).replace(/[${}]/g, '')}</b></span>)}
          {produced.map((name) => <span key={name}>yields <b>{name}</b></span>)}
          {step.has_body || step.body != null ? <span>json body</span> : null}
          {!consumed.length && !produced.length && !(step.has_body || step.body != null) ? <span>no payload</span> : null}
        </div>
      </div>
    })}
  </div>
}

import { Activity, BarChart3, Beaker, BookOpen, List, PenLine, ScrollText, TriangleAlert } from 'lucide-react'

/* A narrow rail rather than a sidebar of labels: the workspace is the content, and the
   navigation is a margin. The provider state is set vertically at the foot because it is
   a standing condition of the workspace, not a notification. */
export type View = 'brief' | 'run' | 'log' | 'experiments' | 'baselines' | 'incidents' | 'audit'

const ITEMS: Array<[View, typeof Activity, string]> = [
  ['brief', PenLine, 'brief'],
  ['run', Activity, 'run'],
  ['log', List, 'log'],
  ['experiments', Beaker, 'trials'],
  ['baselines', BarChart3, 'baselines'],
  ['incidents', TriangleAlert, 'flags'],
  ['audit', ScrollText, 'audit'],
]

export function Rail({ view, onNavigate, provider }: { view: View; onNavigate: (view: View) => void; provider?: string }) {
  return <aside className="rail">
    <a className="rail-mark" href="/" aria-label="LoadPilot home">LP</a>
    <nav aria-label="Workspace">
      {ITEMS.map(([key, Glyph, label]) => <button key={key} className={view === key ? 'rail-item on' : 'rail-item'} aria-current={view === key ? 'page' : undefined} onClick={() => onNavigate(key)}>
        <Glyph size={17} strokeWidth={1.6} aria-hidden="true" /><span>{label}</span>
      </button>)}
    </nav>
    <div className="rail-foot">
      <span className={provider ? 'rail-provider live' : 'rail-provider'}>{provider ? provider : 'deterministic'}</span>
      <a href="/docs" aria-label="API documentation" title="API documentation"><BookOpen size={16} strokeWidth={1.6} /></a>
    </div>
  </aside>
}

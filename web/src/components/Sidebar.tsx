import { Activity, BarChart3, Beaker, BookOpen, LayoutDashboard, Plus, ScrollText, TriangleAlert } from 'lucide-react'
import { Icon } from './Icon'

const items = [
  ['Dashboard', LayoutDashboard], ['New test', Plus], ['Runs', Activity], ['Experiments', Beaker],
  ['Baselines', BarChart3], ['Incidents', TriangleAlert], ['Audit', ScrollText],
] as const

export function Sidebar({ active, onNavigate }: { active: string; onNavigate: (item: string) => void }) {
  return <aside className="sidebar">
    <a className="wordmark" href="/" aria-label="LoadPilot home"><span className="brand-initials">LP</span><span className="brand-name">LoadPilot</span></a>
    <nav aria-label="Primary navigation">
      {items.map(([label, icon]) => <button aria-label={label} title={label} aria-current={active === label ? 'page' : undefined} key={label} className={active === label ? 'nav-item active' : 'nav-item'} onClick={() => onNavigate(label)}>
        <Icon source={icon} /><span>{label}</span>
      </button>)}
    </nav>
    <div className="sidebar-foot">
      <a className="workspace" href="/docs"><BookOpen size={17} /> API documentation</a>
      <div className="identity"><span>LP</span><div><strong>LoadPilot</strong><small>Local workspace</small></div></div>
    </div>
  </aside>
}


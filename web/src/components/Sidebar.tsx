import { Activity, BarChart3, Beaker, BookOpen, Gauge, LayoutDashboard, Plus, ScrollText, TriangleAlert } from 'lucide-react'
import { Icon } from './Icon'

const items = [
  ['Dashboard', LayoutDashboard], ['New test', Plus], ['Runs', Activity], ['Experiments', Beaker],
  ['Baselines', BarChart3], ['Incidents', TriangleAlert], ['Audit', ScrollText],
] as const

export function Sidebar({ active, onNavigate }: { active: string; onNavigate: (item: string) => void }) {
  return <aside className="sidebar">
    <div className="wordmark"><Gauge size={23} strokeWidth={2.2} />Load<span>Pilot</span></div>
    <nav aria-label="Primary navigation">
      {items.map(([label, icon]) => <button key={label} className={active === label ? 'nav-item active' : 'nav-item'} onClick={() => onNavigate(label)}>
        <Icon source={icon} /><span>{label}</span>
      </button>)}
    </nav>
    <div className="sidebar-foot">
      <div className="workspace"><BookOpen size={17} /> Platform team</div>
      <div className="identity"><span>SD</span><div><strong>Sandeep</strong><small>Local workspace</small></div></div>
    </div>
  </aside>
}


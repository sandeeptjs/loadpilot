import type { LucideIcon } from 'lucide-react'

export function Icon({ source: Source, size = 18 }: { source: LucideIcon; size?: number }) {
  return <Source aria-hidden="true" size={size} strokeWidth={1.7} />
}


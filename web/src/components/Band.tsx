import type { ReactNode } from 'react'

/* The workspace is a vertical run of bands rather than a grid of cards: an index, a
   title, a rule that runs to the edge, and a note on the far right. It is the landing
   page's own device, which is why the two halves of the product read as one object. */
export function Band({ index, title, lead, note, tint, children }: { index: string; title: string; lead?: string; note?: ReactNode; tint?: boolean; children: ReactNode }) {
  return <section className={tint ? 'band tint' : 'band'}>
    <div className="band-head">
      <span className="band-index">{index}</span>
      <div><h2>{title}</h2>{lead && <p>{lead}</p>}</div>
      <div className="band-rule" />
      {note !== undefined && note !== null && <span className="band-note">{note}</span>}
    </div>
    {children}
  </section>
}

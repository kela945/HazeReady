import { useEffect, useRef, useState } from 'react'
import type { Citation, DocResponse } from '../types'

/**
 * Citation side panel. Opens the source document scrolled to the exact
 * char_span the claim came from, with the span highlighted.
 */
export default function SourcePanel({
  citation,
  onClose,
}: {
  citation: Citation | null
  onClose: () => void
}) {
  const [doc, setDoc] = useState<DocResponse | null>(null)
  const [error, setError] = useState('')
  const markRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!citation) return
    setDoc(null)
    setError('')
    fetch(`/api/doc/${citation.doc_id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setDoc)
      .catch((e) => setError(String(e)))
  }, [citation])

  useEffect(() => {
    if (doc && markRef.current) {
      markRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [doc])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!citation) return null

  const [start, end] = citation.char_span
  const body = doc?.body ?? ''
  const before = body.slice(0, start)
  const span = body.slice(start, end)
  const after = body.slice(end)

  return (
    <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal="true">
      <div className="flex-1 bg-black/50" onClick={onClose} />
      <aside className="w-full max-w-[620px] bg-panel border-l hairline flex flex-col">
        <div className="px-4 py-3 border-b hairline flex items-start gap-3">
          <div className="min-w-0">
            <div className="label">
              {citation.issuing_agency} · tier {citation.authority_tier}
            </div>
            <h2 className="text-[15px] font-medium mt-0.5 leading-snug">
              {doc?.title ?? citation.title}
            </h2>
            <div className="text-[11px] text-ink-mute num mt-1">
              {citation.doc_id} · chars {start}–{end} · retrieved{' '}
              {citation.retrieved_at}
            </div>
          </div>
          <button onClick={onClose} className="btn !py-1 !px-2 ml-auto shrink-0">
            Esc
          </button>
        </div>

        {doc && (
          <div className="px-4 py-2 border-b hairline text-[11px] text-ink-mute space-y-0.5">
            <div>
              <span className="label">provenance</span>{' '}
              <span className="num">{doc.provenance}</span>
              {!doc.verified_against_source && (
                <span className="ml-2 text-[#8a6a12]">
                  · not verified against a retrieved source page
                </span>
              )}
            </div>
            <div>
              <span className="label">licence</span> {doc.licence}
            </div>
            {doc.source_url && (
              <div>
                <span className="label">source</span>{' '}
                <a
                  href={doc.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2 hover:text-ink break-all"
                >
                  {doc.source_url}
                </a>
              </div>
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {error && <p className="text-[#a8321f] text-[13px]">Failed to load: {error}</p>}
          {!doc && !error && <p className="label">loading document…</p>}
          {doc && (
            <pre className="whitespace-pre-wrap font-mono text-[12.5px] leading-relaxed text-ink-soft">
              {before}
              <mark
                ref={markRef as never}
                className="bg-[#d8ecc8] text-ink rounded px-0.5"
              >
                {span}
              </mark>
              {after}
            </pre>
          )}
        </div>
      </aside>
    </div>
  )
}

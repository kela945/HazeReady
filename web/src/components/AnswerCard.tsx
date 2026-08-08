import { useState } from 'react'
import { bandStyle, decisionStyle } from '../band'
import type { Advisory, Citation } from '../types'

export default function AnswerCard({
  a,
  onCite,
}: {
  a: Advisory
  onCite: (c: Citation) => void
}) {
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null)
  const [reason, setReason] = useState('')
  const [reasonOpen, setReasonOpen] = useState(false)
  const d = decisionStyle(a.decision)
  const b = bandStyle(a.band_result?.band)

  async function send(rating: 'up' | 'down', text = '') {
    setFeedback(rating)
    await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query_id: a.query_id, rating, reason: text }),
    }).catch(() => undefined)
  }

  // Abstention must look deliberate, not broken.
  if (a.decision === 'abstain' && a.abstention) {
    return (
      <div
        className="panel p-4 border-l-[3px]"
        style={{ borderLeftColor: d.fg }}
      >
        <div className="flex items-center gap-2 mb-2">
          <span
            className="text-[12px] font-semibold tracking-wide px-2 py-1 rounded border"
            style={{ color: d.fg, background: d.bg, borderColor: d.border }}
          >
            <span aria-hidden="true">{d.glyph}</span> NO GOVERNING GUIDANCE
          </span>
          <span className="label">
            reason: {a.abstention.reason.replace(/_/g, ' ')}
          </span>
        </div>

        <p className="text-[14px] leading-relaxed text-ink">
          {a.abstention.plain_language}
        </p>

        <div className="mt-3 p-3 rounded-md border hairline bg-subtle">
          <div className="label mb-1">who can answer this</div>
          <p className="text-[13.5px] text-ink">
            {a.abstention.suggested_authority}
          </p>
        </div>

        <p className="mt-3 text-[12px] text-ink-mute leading-relaxed">
          This is a deliberate refusal, not a failure. The system declines rather
          than inventing a threshold, because a confident wrong number during a
          health episode is worse than no answer.
          {a.abstention.evidence_doc_id && (
            <>
              {' '}
              The absence of guidance is recorded in{' '}
              <code className="text-[#2b5d8a]">
                {a.abstention.evidence_doc_id}
              </code>
              .
            </>
          )}
        </p>

        <Feedback
          feedback={feedback}
          send={send}
          reason={reason}
          setReason={setReason}
          reasonOpen={reasonOpen}
          setReasonOpen={setReasonOpen}
        />
      </div>
    )
  }

  return (
    <div className="panel overflow-hidden">
      <div
        className="px-4 py-3 flex items-center gap-3 flex-wrap border-b hairline"
        style={{ background: d.bg }}
      >
        <span
          className="text-[15px] font-semibold tracking-wide px-2.5 py-1 rounded border"
          style={{ color: d.fg, background: d.bg, borderColor: d.border }}
        >
          <span aria-hidden="true">{d.glyph}</span> {a.decision_label}
        </span>
        {a.band_result && (
          <span className="text-[12px] text-ink-mute num">
            {a.band_result.index === 'psi_24h' ? '24-h PSI' : '1-h PM2.5'}{' '}
            <b style={{ color: b.fg }}>{a.band_result.value}</b> ={' '}
            <span style={{ color: b.fg }}>{b.label}</span>
          </span>
        )}
        <span className="label ml-auto">
          role: {a.role.replace(/_/g, ' ')}
          {a.role_routed_by === 'router' &&
            ` · routed (${a.router_confidence.toFixed(2)})`}
        </span>
      </div>

      <div className="p-4 space-y-4">
        {a.band_result?.boundary_note && (
          <div className="text-[12px] text-[#8a6a12] border border-[#e0d2a8] bg-[#fdf6e3] rounded px-2.5 py-1.5">
            {a.band_result.boundary_note}
          </div>
        )}

        {a.conflicts.length > 0 && (
          <div className="text-[12.5px] border border-[#e0d2a8] bg-[#fdf6e3] rounded px-2.5 py-2">
            <div className="label mb-1">conflicting primary sources</div>
            {a.conflicts.map((c, i) => (
              <p key={i} className="text-ink">
                {c}
              </p>
            ))}
          </div>
        )}

        {a.obligations.length > 0 && (
          <div>
            <div className="label mb-1.5">what you must do</div>
            <ul className="space-y-1.5">
              {a.obligations.map((o, i) => (
                <li key={i} className="flex gap-2.5 text-[14px] leading-relaxed">
                  <span
                    className="mt-[3px] w-3.5 h-3.5 shrink-0 rounded-sm border hairline"
                    aria-hidden="true"
                  />
                  <span className="text-ink">{o}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {a.rationale && (
          <div>
            <div className="label mb-1">reasoning</div>
            <p className="text-[13.5px] leading-relaxed text-ink-soft">
              {a.rationale}
            </p>
          </div>
        )}

        {a.citations.length > 0 && (
          <div>
            <div className="label mb-1.5">sources</div>
            <div className="flex flex-wrap gap-1.5">
              {a.citations.map((c) => (
                <button
                  key={c.doc_id}
                  onClick={() => onCite(c)}
                  className="chip !py-1 !text-[12px] flex items-center gap-1.5"
                  title={`${c.title} — ${c.issuing_agency}, retrieved ${c.retrieved_at}`}
                >
                  <sup className="num text-[#2b5d8a]">{c.marker}</sup>
                  <span className="text-ink">{c.issuing_agency}</span>
                  <span className="text-ink-mute truncate max-w-[220px]">
                    {c.title}
                  </span>
                  {c.authority_tier !== 'primary' && (
                    <span className="label !text-[9px]">{c.authority_tier}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 pt-1 text-[11px] text-ink-mute num flex-wrap">
          <span>{a.latency_ms} ms</span>
          <span>·</span>
          <span>
            {a.provider}/{a.model}
          </span>
          {a.prompt_tokens > 0 && (
            <>
              <span>·</span>
              <span>
                {a.prompt_tokens}+{a.completion_tokens} tok
              </span>
            </>
          )}
          <span>·</span>
          <span>retrieval {a.top_retrieval_score.toFixed(4)}</span>
        </div>

        <Feedback
          feedback={feedback}
          send={send}
          reason={reason}
          setReason={setReason}
          reasonOpen={reasonOpen}
          setReasonOpen={setReasonOpen}
        />
      </div>
    </div>
  )
}

function Feedback({
  feedback,
  send,
  reason,
  setReason,
  reasonOpen,
  setReasonOpen,
}: {
  feedback: 'up' | 'down' | null
  send: (r: 'up' | 'down', t?: string) => void
  reason: string
  setReason: (s: string) => void
  reasonOpen: boolean
  setReasonOpen: (b: boolean) => void
}) {
  return (
    <div className="pt-3 border-t hairline">
      {feedback === null ? (
        <div className="flex items-center gap-2">
          <span className="label">was this correct?</span>
          <button onClick={() => send('up')} className="btn !py-1 !text-[12px]">
            Yes
          </button>
          <button
            onClick={() => {
              setReasonOpen(true)
            }}
            className="btn !py-1 !text-[12px]"
          >
            No
          </button>
        </div>
      ) : (
        <span className="label">
          feedback recorded — thank you
        </span>
      )}
      {reasonOpen && feedback === null && (
        <div className="mt-2 flex gap-2">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="What was wrong? (optional)"
            className="flex-1 bg-subtle border hairline rounded-md px-2.5 py-1.5 text-[13px] outline-none focus:border-line-strong"
          />
          <button
            onClick={() => {
              send('down', reason)
              setReasonOpen(false)
            }}
            className="btn !py-1 !text-[12px]"
          >
            Send
          </button>
        </div>
      )}
    </div>
  )
}

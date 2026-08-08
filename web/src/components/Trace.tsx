import { useState } from 'react'
import type { GuardrailEvent, ToolCall } from '../types'

interface Step {
  type: string
  [k: string]: unknown
}

/**
 * The reasoning trace. This is the most persuasive element in the interface:
 * it shows the band arriving from a deterministic function call, not from the
 * language model. Collapsed by default; streams live while a query runs.
 */
export default function Trace({
  steps,
  trajectory,
  guardrails,
  running,
  llmError,
}: {
  steps: Step[]
  trajectory: ToolCall[]
  guardrails: GuardrailEvent[]
  running: boolean
  llmError?: string
}) {
  const [open, setOpen] = useState(false)
  const has = steps.length > 0 || trajectory.length > 0

  if (!has && !running) return null

  return (
    <div className="panel">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="label">reasoning trace</span>
        {running && (
          <span className="text-[11px] text-[#1f6f52] num live-dot">running…</span>
        )}
        {!running && trajectory.length > 0 && (
          <span className="text-[11px] text-ink-mute num">
            {trajectory.length} tool calls ·{' '}
            {guardrails.filter((g) => g.triggered).length} guardrails fired
          </span>
        )}
        <span className="ml-auto text-ink-mute text-[11px]">
          {open ? '▾ hide' : '▸ show'}
        </span>
      </button>

      {/* A degraded answer must announce itself, collapsed or not. */}
      {llmError && (
        <div className="px-3 pb-2 text-[11.5px] text-[#a8321f] leading-snug">
          Language model unavailable — this answer was composed from the
          deterministic policy matrix only.{' '}
          <span className="font-mono text-ink-mute">{llmError}</span>
        </div>
      )}

      {/* While running, always show the live step feed even when collapsed. */}
      {(open || running) && (
        <div className="border-t hairline px-3 py-2.5 space-y-1 max-h-[340px] overflow-y-auto">
          {trajectory.length > 0
            ? trajectory.map((t) => (
                <div key={t.hop} className="font-mono text-[11.5px] leading-relaxed">
                  <span className="text-ink-mute">{String(t.hop).padStart(2, '0')}</span>{' '}
                  <span className={t.ok ? 'text-[#2b5d8a]' : 'text-[#a8321f]'}>
                    {t.tool}
                  </span>
                  <span className="text-ink-mute">
                    (
                    {Object.entries(t.arguments)
                      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                      .join(', ')}
                    )
                  </span>{' '}
                  <span className="text-ink-mute">→</span>{' '}
                  <span className="text-ink-soft">{t.result_summary}</span>{' '}
                  <span className="text-ink-mute">[{t.latency_ms}ms]</span>
                </div>
              ))
            : steps.map((s, i) => (
                <div key={i} className="font-mono text-[11.5px] text-ink-soft">
                  <span className="text-ink-mute">{String(i + 1).padStart(2, '0')}</span>{' '}
                  <span className="text-[#2b5d8a]">{s.type}</span>{' '}
                  <span className="text-ink-mute">
                    {JSON.stringify(
                      Object.fromEntries(
                        Object.entries(s).filter(([k]) => k !== 'type'),
                      ),
                    )}
                  </span>
                </div>
              ))}

          {open && guardrails.length > 0 && (
            <div className="pt-2 mt-2 border-t hairline">
              <div className="label mb-1">guardrail chain</div>
              {guardrails.map((g, i) => (
                <div key={i} className="font-mono text-[11.5px] leading-relaxed">
                  <span
                    className={g.triggered ? 'text-[#8a6a12]' : 'text-[#1f6f52]'}
                    aria-hidden="true"
                  >
                    {g.triggered ? '!' : '✓'}
                  </span>{' '}
                  <span className="text-ink-soft">{g.guardrail}</span>{' '}
                  <span className="text-ink-mute">
                    {g.triggered ? `${g.action}: ${g.detail}` : 'pass'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

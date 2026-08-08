import { useCallback, useEffect, useRef, useState } from 'react'
import AnswerCard from '../components/AnswerCard'
import SourcePanel from '../components/SourcePanel'
import SingaporeMap from '../components/SingaporeMap'
import StatusStrip from '../components/StatusStrip'
import Trace from '../components/Trace'
import type { Advisory, Citation, Conditions, RoleId } from '../types'

const ROLES: { id: RoleId; label: string }[] = [
  { id: 'general_public', label: 'Public' },
  { id: 'preschool', label: 'Preschool' },
  { id: 'school', label: 'School' },
  { id: 'eldercare', label: 'Eldercare' },
  { id: 'worksite', label: 'Worksite' },
  { id: 'event', label: 'Event' },
]

export default function Console() {
  const [conditions, setConditions] = useState<Conditions | null>(null)
  const [role, setRole] = useState<RoleId>('preschool')
  const [examples, setExamples] = useState<string[]>([])
  const [question, setQuestion] = useState('')
  const [advisory, setAdvisory] = useState<Advisory | null>(null)
  const [steps, setSteps] = useState<{ type: string }[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [citation, setCitation] = useState<Citation | null>(null)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    fetch('/api/conditions')
      .then((r) => r.json())
      .then(setConditions)
      .catch(() => setError('Could not load current conditions.'))
    const t = setInterval(() => {
      fetch('/api/conditions')
        .then((r) => r.json())
        .then(setConditions)
        .catch(() => undefined)
    }, 60_000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    fetch(`/api/examples?role=${role}`)
      .then((r) => r.json())
      .then(setExamples)
      .catch(() => setExamples([]))
  }, [role])

  const ask = useCallback(
    (q: string) => {
      if (!q.trim() || running) return
      setRunning(true)
      setAdvisory(null)
      setSteps([])
      setError('')
      esRef.current?.close()

      const url = `/api/ask/stream?question=${encodeURIComponent(q)}&role=${role}`
      const es = new EventSource(url)
      esRef.current = es

      es.addEventListener('step', (e) => {
        setSteps((s) => [...s, JSON.parse((e as MessageEvent).data)])
      })
      es.addEventListener('advisory', (e) => {
        setAdvisory(JSON.parse((e as MessageEvent).data))
        setRunning(false)
        es.close()
      })
      es.addEventListener('error', () => {
        setError('The request failed. Check the server logs.')
        setRunning(false)
        es.close()
      })
    },
    [role, running],
  )

  useEffect(() => () => esRef.current?.close(), [])

  return (
    <div className="space-y-4">
      <StatusStrip c={conditions} />

      <SingaporeMap c={conditions} />

      {conditions?.offline_mode && (
        <div className="panel px-3 py-2 text-[12px] text-[#8a6a12]">
          OFFLINE_MODE is on — readings are served from committed fixtures, not
          from data.gov.sg.
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-4">
        <div className="space-y-4">
          {/* Role is explicit and visible at all times: the answer depends on it. */}
          <div className="panel p-3">
            <div className="label mb-2">
              asking as — the answer depends on this
            </div>
            <div
              role="radiogroup"
              aria-label="Operational role"
              className="grid grid-cols-3 sm:grid-cols-6 gap-1"
            >
              {ROLES.map((r) => (
                <button
                  key={r.id}
                  role="radio"
                  aria-checked={role === r.id}
                  onClick={() => setRole(r.id)}
                  className={`px-2 py-2 text-[12.5px] rounded-md border transition-colors ${
                    role === r.id
                      ? 'bg-active border-line-strong text-ink font-medium'
                      : 'border-line text-ink-mute hover:text-ink'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          <div className="panel p-3">
            <form
              onSubmit={(e) => {
                e.preventDefault()
                ask(question)
              }}
              className="flex gap-2"
            >
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Describe the decision you need to make…"
                aria-label="Your question"
                className="flex-1 bg-subtle border hairline rounded-md px-3 py-2.5 text-[14px] outline-none focus:border-line-strong"
              />
              <button
                type="submit"
                disabled={running || !question.trim()}
                className="btn !px-4 disabled:opacity-40"
              >
                {running ? 'Working…' : 'Ask'}
              </button>
            </form>

            {examples.length > 0 && (
              <div className="mt-2.5">
                <div className="label mb-1.5">try one of these</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                  {examples.map((ex) => (
                    <button
                      key={ex}
                      onClick={() => {
                        setQuestion(ex)
                        ask(ex)
                      }}
                      className="chip"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <Trace
            steps={steps}
            trajectory={advisory?.trajectory ?? []}
            guardrails={advisory?.guardrail_events ?? []}
            running={running}
            llmError={advisory?.llm_error}
          />

          {error && (
            <div className="panel p-3 text-[13px] text-[#a8321f]">{error}</div>
          )}

          {advisory && <AnswerCard a={advisory} onCite={setCitation} />}
        </div>

        {/* Side rail: what governs this role */}
        <aside className="space-y-4">
          <RoleBrief role={role} />
        </aside>
      </div>

      <SourcePanel citation={citation} onClose={() => setCitation(null)} />
    </div>
  )
}

function RoleBrief({ role }: { role: RoleId }) {
  const [info, setInfo] = useState<{
    description: string
    governing_agencies: string[]
    primary_index: string
    known_gaps: string
  } | null>(null)

  useEffect(() => {
    fetch('/api/roles')
      .then((r) => r.json())
      .then((rows) => setInfo(rows.find((x: { role: string }) => x.role === role) ?? null))
      .catch(() => setInfo(null))
  }, [role])

  if (!info) return null
  return (
    <div className="panel p-3 space-y-3">
      <div>
        <div className="label mb-1">governing skill</div>
        <p className="text-[12.5px] text-ink-soft leading-relaxed">
          {info.description}
        </p>
      </div>
      <div className="flex gap-4">
        <div>
          <div className="label mb-1">agencies</div>
          <div className="text-[12px] num text-ink">
            {info.governing_agencies.join(' · ')}
          </div>
        </div>
        <div>
          <div className="label mb-1">index</div>
          <div className="text-[12px] num text-ink">
            {info.primary_index === 'psi_24h' ? '24-h PSI' : '1-h PM2.5'}
          </div>
        </div>
      </div>
      {info.known_gaps && (
        <div>
          <div className="label mb-1">known gaps — the system abstains on these</div>
          <p className="text-[12px] text-ink-mute leading-relaxed">
            {info.known_gaps}
          </p>
        </div>
      )}
    </div>
  )
}

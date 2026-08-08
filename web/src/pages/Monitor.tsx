import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

interface Summary {
  total_queries: number
  empty?: boolean
  latency_ms?: { p50: number; p95: number; p99: number }
  abstention_rate?: number
  tokens?: { prompt: number; completion: number }
  by_role?: Record<string, number>
  by_decision?: Record<string, number>
  guardrail_triggers?: Record<string, number>
  out_of_corpus_queries?: number
  out_of_corpus_rate?: number
  mean_top_retrieval_score?: number
  feedback?: Record<string, number>
  negative_feedback_rate?: number
  tool_call_distribution?: Record<string, number>
  upstream_live?: Record<string, unknown>
  config?: Record<string, unknown>
}

interface EventRow {
  id: number
  ts: string
  query_id: string
  role: string
  decision: string
  latency_ms: number
  top_retrieval_score: number
  abstained: number
  payload: { question?: string; tools?: string[]; citations?: string[]; band?: string }
}

const REFRESH_MS = 15_000

export default function Monitor() {
  const [s, setS] = useState<Summary | null>(null)
  const [events, setEvents] = useState<EventRow[]>([])
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    function load() {
      fetch('/api/metrics/summary')
        .then((r) => r.json())
        .then(setS)
        .catch(() => undefined)
      fetch('/api/metrics/events?limit=50')
        .then((r) => r.json())
        .then(setEvents)
        .catch(() => undefined)
    }
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [])

  if (!s) return <div className="label">loading metrics…</div>

  if (s.empty || s.total_queries === 0) {
    return (
      <div className="panel p-6">
        <h2 className="text-[15px] mb-2">No telemetry yet</h2>
        <p className="text-[13px] text-ink-mute leading-relaxed max-w-[60ch]">
          Ask a few questions on the Advisory console and this dashboard will
          populate. Nothing here is seeded or simulated — every number comes from
          real requests recorded in the local SQLite store.
        </p>
      </div>
    )
  }

  const costIn = Number(s.config?.cost_per_1m_input_usd ?? 0)
  const costOut = Number(s.config?.cost_per_1m_output_usd ?? 0)
  const tokensPrompt = s.tokens?.prompt ?? 0
  const tokensCompletion = s.tokens?.completion ?? 0
  const spend = (tokensPrompt / 1e6) * costIn + (tokensCompletion / 1e6) * costOut
  const costPerQuery = spend / Math.max(1, s.total_queries)

  // `disclaimer_injection` fires on 100% of requests by construction — it is a
  // constant, not a signal. Including it makes the headline count meaningless
  // and scales the chart axis so the guardrails an operator actually needs to
  // watch (entailment strips, numeric rejections, over-permission blocks)
  // render sub-pixel.
  const allTriggers = s.guardrail_triggers ?? {}
  const disclaimerCount = allTriggers['disclaimer_injection'] ?? 0
  const realTriggers = Object.fromEntries(
    Object.entries(allTriggers).filter(([k]) => k !== 'disclaimer_injection'),
  )
  const realTriggerTotal = Object.values(realTriggers).reduce((a, b) => a + b, 0)

  const filtered = events.filter(
    (e) =>
      !filter ||
      e.role?.includes(filter) ||
      e.decision?.includes(filter) ||
      (e.payload.question ?? '').toLowerCase().includes(filter.toLowerCase()),
  )

  return (
    <div className="space-y-4">
      <Row label="1 — service health">
        <Stat v={String(s.total_queries)} l="queries served" />
        <Stat v={`${s.latency_ms?.p50 ?? 0}`} l="p50 latency (ms)" />
        <Stat v={`${s.latency_ms?.p95 ?? 0}`} l="p95 latency (ms)" />
        <Stat v={`${s.latency_ms?.p99 ?? 0}`} l="p99 latency (ms)" />
        <Stat
          v={String(s.config?.provider ?? '—')}
          l="llm provider"
          note={String(s.config?.model ?? '')}
        />
      </Row>

      <div className="panel p-3">
        <div className="label mb-2">upstream status</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[12px]">
          {Object.entries((s.upstream_live ?? {}) as Record<string, unknown>)
            .filter(([k]) => k !== 'errors')
            .map(([name, last]) => (
              <div
                key={name}
                className="border hairline rounded-md px-2.5 py-2 flex items-center gap-2"
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: last ? '#1f6f52' : '#78756c' }}
                />
                <span className="num truncate">{name}</span>
                <span className="text-ink-mute ml-auto num text-[11px]">
                  {last ? new Date(String(last)).toLocaleTimeString() : 'no call yet'}
                </span>
              </div>
            ))}
        </div>
        {s.config?.offline_mode ? (
          <p className="text-[11px] text-[#8a6a12] mt-2">
            OFFLINE_MODE is on — upstreams are not called; fixtures are served.
          </p>
        ) : null}
      </div>

      <Row label="2 — ai quality">
        <Stat
          v={`${((s.abstention_rate ?? 0) * 100).toFixed(1)}%`}
          l="abstention rate"
        />
        <Stat
          v={String(realTriggerTotal)}
          l="guardrail interventions"
          note={`disclaimer injected on all ${disclaimerCount}`}
        />
        <Stat
          v={(s.mean_top_retrieval_score ?? 0).toFixed(4)}
          l="mean retrieval score"
        />
        <Stat
          v={`${((s.negative_feedback_rate ?? 0) * 100).toFixed(0)}%`}
          l="negative feedback"
          note={`${s.feedback?.down ?? 0} of ${
            (s.feedback?.up ?? 0) + (s.feedback?.down ?? 0)
          }`}
        />
      </Row>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Chart
          title="guardrail interventions by type (disclaimer excluded — fires on every request)"
          data={Object.entries(realTriggers).map(([k, v]) => ({
            name: k.replace(/_/g, ' '),
            v,
          }))}
          colour="#8a6a12"
        />
        <Chart
          title="tool call distribution"
          data={Object.entries(s.tool_call_distribution ?? {}).map(([k, v]) => ({
            name: k.replace(/_/g, ' '),
            v,
          }))}
          colour="#2b5d8a"
        />
      </div>

      <Row label="3 — drift and safety">
        <Stat
          v={String(s.out_of_corpus_queries ?? 0)}
          l="out-of-corpus queries"
          note={`below score ${s.config?.out_of_corpus_threshold}`}
        />
        <Stat
          v={`${((s.out_of_corpus_rate ?? 0) * 100).toFixed(1)}%`}
          l="out-of-corpus rate"
          note="early warning that guidance changed"
        />
        <Stat
          v={String(Object.keys(s.by_role ?? {}).length)}
          l="distinct roles seen"
        />
        <Stat
          v={String(s.by_decision?.abstain ?? 0)}
          l="abstentions"
        />
      </Row>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Chart
          title="queries by role"
          data={Object.entries(s.by_role ?? {}).map(([k, v]) => ({
            name: k.replace(/_/g, ' '),
            v,
          }))}
          colour="#1f6f52"
        />
        <Chart
          title="decisions issued"
          data={Object.entries(s.by_decision ?? {}).map(([k, v]) => ({
            name: k.replace(/_/g, ' '),
            v,
          }))}
          colour="#b4530f"
        />
      </div>

      <Row label="4 — cost">
        <Stat v={String(tokensPrompt + tokensCompletion)} l="tokens total" />
        <Stat v={`$${spend.toFixed(4)}`} l="spend at configured rate" />
        <Stat v={`$${costPerQuery.toFixed(5)}`} l="cost per resolved query" />
        <Stat
          v={`$${(costPerQuery * 1000).toFixed(2)}`}
          l="projected per 1,000 queries"
        />
      </Row>
      {costIn === 0 && costOut === 0 && (
        <p className="text-[11px] text-ink-mute">
          LLM_COST_IN and LLM_COST_OUT are unset, so cost reports as $0 rather
          than a fabricated figure. Set them to the published rate for the model
          in use.
        </p>
      )}

      <div className="panel">
        <div className="px-3 py-2 border-b hairline flex items-center gap-3">
          <span className="label">live event stream — last 50</span>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="filter by role, decision or text"
            className="ml-auto bg-subtle border hairline rounded px-2 py-1 text-[12px] outline-none focus:border-line-strong w-[240px]"
          />
        </div>
        <div className="max-h-[420px] overflow-y-auto">
          {filtered.map((e) => (
            <div key={e.id} className="border-b hairline last:border-0">
              <button
                onClick={() => setExpanded(expanded === e.id ? null : e.id)}
                className="w-full text-left px-3 py-2 flex items-center gap-3 text-[12px] hover:bg-subtle"
              >
                <span className="num text-ink-mute shrink-0">
                  {new Date(e.ts).toLocaleTimeString()}
                </span>
                <span className="num text-[#2b5d8a] shrink-0 w-[92px]">{e.role}</span>
                <span
                  className={`num shrink-0 w-[150px] ${
                    e.abstained ? 'text-[#2b5d8a]' : 'text-ink'
                  }`}
                >
                  {e.decision}
                </span>
                <span className="truncate text-ink-mute">
                  {e.payload.question}
                </span>
                <span className="num text-ink-mute ml-auto shrink-0">
                  {e.latency_ms}ms
                </span>
              </button>
              {expanded === e.id && (
                <div className="px-3 pb-3 text-[11.5px] font-mono text-ink-mute space-y-1">
                  <div>
                    <span className="label">trajectory</span>{' '}
                    {(e.payload.tools ?? []).join(' → ') || 'none'}
                  </div>
                  <div>
                    <span className="label">citations</span>{' '}
                    {(e.payload.citations ?? []).join(', ') || 'none'}
                  </div>
                  <div>
                    <span className="label">band</span> {e.payload.band ?? '—'}
                  </div>
                  <div>
                    <span className="label">retrieval</span>{' '}
                    {e.top_retrieval_score?.toFixed(5)}
                  </div>
                  <div>
                    <span className="label">query id</span> {e.query_id}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <p className="text-[11px] text-ink-mute leading-relaxed max-w-[85ch]">
        Nothing here is redacted because nothing sensitive is collected: no
        accounts, no session persistence beyond a per-query UUID, and no personal
        data fields exist in the telemetry schema. <code>GET /metrics</code>{' '}
        exposes the same counters in Prometheus text format — that is the
        integration point for real observability infrastructure, which is
        deliberately not implemented here.
      </p>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="label mb-1.5">{label}</div>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-5 gap-2">
        {children}
      </div>
    </div>
  )
}

function Stat({ v, l, note }: { v: string; l: string; note?: string }) {
  return (
    <div className="panel px-3 py-2.5">
      <div className="num text-[22px] font-semibold leading-tight truncate" title={v}>
        {v}
      </div>
      <div className="text-[11.5px] mt-0.5 text-ink-soft">{l}</div>
      {note && <div className="label mt-0.5 !text-[9px] truncate">{note}</div>}
    </div>
  )
}

function Chart({
  title,
  data,
  colour,
}: {
  title: string
  data: { name: string; v: number }[]
  colour: string
}) {
  if (data.length === 0) {
    return (
      <div className="panel p-3">
        <div className="label mb-2">{title}</div>
        <p className="text-[12px] text-ink-mute">no data yet</p>
      </div>
    )
  }
  return (
    <div className="panel p-3">
      <div className="label mb-2">{title}</div>
      <ResponsiveContainer width="100%" height={190}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -22, bottom: 4 }}>
          <CartesianGrid stroke="#e3e0d8" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fill: '#78756c', fontSize: 10 }}
            axisLine={{ stroke: '#e3e0d8' }}
            tickLine={false}
            interval={0}
            angle={-18}
            textAnchor="end"
            height={54}
          />
          <YAxis
            tick={{ fill: '#78756c', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            cursor={{ fill: '#f3f1ec' }}
            contentStyle={{
              background: '#ffffff',
              border: '1px solid #e3e0d8',
              borderRadius: 6,
              fontSize: 12,
            }}
          />
          <Bar dataKey="v" radius={[3, 3, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={colour} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

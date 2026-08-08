import { useEffect, useMemo, useState } from 'react'
import { bandStyle, psiBandKey } from '../band'
import type { Conditions } from '../types'

interface History {
  timestamps: string[]
  regions: Record<string, (number | null)[]>
  source: string
  hours: number
}

const REGIONS = ['north', 'south', 'east', 'west', 'central'] as const
type RegionName = (typeof REGIONS)[number]

/**
 * NEA reporting-region label locations, straight from the data.gov.sg
 * `region_metadata` payload. Using the published coordinates rather than
 * eyeballed positions means the dots sit where NEA says the regions are.
 */
const REGION_LATLON: Record<RegionName, [number, number]> = {
  north: [1.41803, 103.82],
  south: [1.29587, 103.82],
  east: [1.35735, 103.94],
  west: [1.35735, 103.7],
  central: [1.35735, 103.82],
}

// Bounding box for the projection, framing the main island with a small margin.
const LON0 = 103.593
const LON1 = 104.057
const LAT0 = 1.228
const LAT1 = 1.487

// Height is derived from the box rather than picked, so the island is not
// silently stretched. At ~1.35°N a degree of longitude is 111.32 km and a
// degree of latitude 110.57 km, which makes the frame 51.6 km by 28.6 km.
const W = 540
const KM_PER_DEG_LON = 111.32
const KM_PER_DEG_LAT = 110.57
const H = Math.round(
  W * (((LAT1 - LAT0) * KM_PER_DEG_LAT) / ((LON1 - LON0) * KM_PER_DEG_LON)),
)

function project(lat: number, lon: number): [number, number] {
  const x = ((lon - LON0) / (LON1 - LON0)) * W
  const y = ((LAT1 - lat) / (LAT1 - LAT0)) * H
  return [x, y]
}

/**
 * Simplified coastline of the Singapore main island, as lon/lat vertices.
 *
 * This is a deliberately stylised outline, not survey data: it exists to give
 * the five reporting regions a recognisable frame, and the readings — not the
 * geometry — are what the panel is for. Anything requiring real geography
 * should use an actual boundary dataset.
 */
const COASTLINE: [number, number][] = [
  // West — the Tuas point
  [103.603, 1.318], [103.612, 1.336], [103.638, 1.353],
  // North-west — Lim Chu Kang
  [103.66, 1.373], [103.685, 1.398], [103.703, 1.425],
  // North — Kranji, Woodlands, Sembawang
  [103.722, 1.441], [103.74, 1.437], [103.755, 1.452], [103.772, 1.461],
  [103.795, 1.466], [103.818, 1.473], [103.84, 1.466],
  // North-east — Seletar, Punggol
  [103.858, 1.455], [103.876, 1.444], [103.895, 1.425], [103.912, 1.412],
  // East — Pasir Ris into the Changi peninsula
  [103.93, 1.398], [103.955, 1.388], [103.975, 1.392], [103.995, 1.39],
  [104.015, 1.382], [104.03, 1.363], [104.032, 1.34],
  // South-east — Changi south, Bedok, East Coast
  [104.02, 1.322], [103.995, 1.313], [103.968, 1.305], [103.94, 1.3],
  [103.91, 1.293],
  // South — Marina, city, Keppel
  [103.885, 1.283], [103.862, 1.272], [103.84, 1.264], [103.818, 1.262],
  // South-west — Pasir Panjang, Jurong, Tuas South
  [103.795, 1.268], [103.772, 1.274], [103.748, 1.281], [103.725, 1.292],
  [103.7, 1.3], [103.672, 1.308], [103.64, 1.31], [103.618, 1.312],
]

// Sentosa, as a small southern satellite — recognisable and cheap to draw.
const SENTOSA: [number, number][] = [
  [103.797, 1.251], [103.82, 1.256], [103.836, 1.251], [103.842, 1.246],
  [103.826, 1.242], [103.806, 1.246],
]

function toPath(pts: [number, number][]): string {
  return (
    pts
      .map(([lon, lat], i) => {
        const [x, y] = project(lat, lon)
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
      })
      .join(' ') + ' Z'
  )
}

/** A compact sparkline for one region's trailing PSI. */
function Spark({
  values,
  colour,
  width = 92,
  height = 26,
}: {
  values: (number | null)[]
  colour: string
  width?: number
  height?: number
}) {
  const clean = values.filter((v): v is number => v !== null && v !== undefined)
  if (clean.length < 2) return null

  // Scale to the series' own range with a floor, so a flat day does not render
  // as noise amplified to full height.
  const lo = Math.min(...clean)
  const hi = Math.max(...clean)
  const span = Math.max(hi - lo, 8)
  const mid = (hi + lo) / 2
  const top = mid + span / 2
  const bottom = mid - span / 2

  const pts = clean.map((v, i) => {
    const x = (i / (clean.length - 1)) * width
    const y = height - ((v - bottom) / (top - bottom)) * height
    return [x, Math.max(1, Math.min(height - 1, y))] as const
  })

  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${line} L${width},${height} L0,${height} Z`
  const [lx, ly] = pts[pts.length - 1]

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden="true">
      <path d={area} fill={colour} opacity={0.13} />
      <path d={line} fill="none" stroke={colour} strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r={2.2} fill={colour} />
    </svg>
  )
}

export default function SingaporeMap({ c }: { c: Conditions | null }) {
  const [hours, setHours] = useState(24)
  const [history, setHistory] = useState<History | null>(null)
  const [hover, setHover] = useState<RegionName | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/psi/history?hours=${hours}`)
      .then((r) => r.json())
      .then((h) => !cancelled && setHistory(h))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [hours])

  const coastPath = useMemo(() => toPath(COASTLINE), [])
  const sentosaPath = useMemo(() => toPath(SENTOSA), [])

  const readings = c?.regions ?? {}

  // Island-wide trend: the change in the worst region over the window. The
  // worst region is what governs an institution's decision, not the average.
  const trend = useMemo(() => {
    if (!history) return null
    const worstAt = (i: number) => {
      const vals = REGIONS.map((r) => history.regions[r]?.[i]).filter(
        (v): v is number => typeof v === 'number',
      )
      return vals.length ? Math.max(...vals) : null
    }
    const n = history.timestamps.length
    if (n < 2) return null
    const first = worstAt(0)
    const last = worstAt(n - 1)
    if (first === null || last === null) return null
    return { delta: last - first, first, last }
  }, [history])

  return (
    <div className="panel overflow-hidden">
      <div className="px-3 py-2 border-b hairline flex items-center gap-3 flex-wrap">
        <span className="label">24-hour PSI by region</span>
        {trend && (
          <span className="text-[11px] num text-ink-mute">
            worst region {trend.first} → {trend.last} over {hours}h{' '}
            <span
              style={{
                color:
                  trend.delta > 2
                    ? '#a8321f'
                    : trend.delta < -2
                      ? '#1f6f52'
                      : '#78756c',
              }}
            >
              {trend.delta > 0 ? `▲ +${trend.delta}` : trend.delta < 0 ? `▼ ${trend.delta}` : '— flat'}
            </span>
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {[24, 48, 72].map((h) => (
            <button
              key={h}
              onClick={() => setHours(h)}
              className={`px-2 py-0.5 text-[11px] num rounded border transition-colors ${
                hours === h
                  ? 'bg-active border-line-strong text-ink'
                  : 'border-line text-ink-mute hover:text-ink'
              }`}
            >
              {h}h
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
        {/* Map. Capped rather than fluid: at full page width the island would
            dominate the console, and the console is for asking questions. */}
        <div className="p-3">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full h-auto max-w-[420px] mx-auto block"
            role="img"
            aria-label="Map of Singapore showing current 24-hour PSI for the five NEA reporting regions"
          >
            {/* Water */}
            <rect x={0} y={0} width={W} height={H} fill="#eef3f5" rx={6} />

            {/* Land */}
            <path d={coastPath} fill="#e6e2d8" stroke="#cfcbc0" strokeWidth={1} />
            <path d={sentosaPath} fill="#e6e2d8" stroke="#cfcbc0" strokeWidth={1} />

            {/* Region markers, sized so overlap reads as adjacency not error */}
            {REGIONS.map((r) => {
              const rd = readings[r]
              const psi = rd?.psi_24h ?? null
              const st = bandStyle(psiBandKey(psi))
              const [lat, lon] = REGION_LATLON[r]
              const [x, y] = project(lat, lon)
              const active = hover === r
              return (
                <g
                  key={r}
                  onMouseEnter={() => setHover(r)}
                  onMouseLeave={() => setHover(null)}
                  style={{ cursor: 'default' }}
                >
                  <circle
                    cx={x}
                    cy={y}
                    r={active ? 34 : 30}
                    fill={st.solid}
                    opacity={0.20}
                  />
                  <circle
                    cx={x}
                    cy={y}
                    r={active ? 23 : 21}
                    fill="#ffffff"
                    stroke={st.solid}
                    strokeWidth={active ? 3 : 2}
                  />
                  <text
                    x={x}
                    y={y + 1}
                    textAnchor="middle"
                    fontSize={16}
                    fontWeight={650}
                    fill={st.fg}
                    fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
                    style={{ fontVariantNumeric: 'tabular-nums' }}
                  >
                    {psi ?? '—'}
                  </text>
                  <text
                    x={x}
                    y={y + 13}
                    textAnchor="middle"
                    fontSize={7.5}
                    fill="#78756c"
                    letterSpacing="0.08em"
                  >
                    {r.toUpperCase()}
                  </text>
                </g>
              )
            })}
          </svg>

          {/* Legend — colour is never the only channel */}
          <div className="flex flex-wrap justify-center gap-x-3 gap-y-1 mt-1.5 px-1">
            {['good', 'moderate', 'unhealthy', 'very_unhealthy', 'hazardous'].map((k) => {
              const st = bandStyle(k)
              return (
                <span key={k} className="flex items-center gap-1 text-[10px] text-ink-mute">
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ background: st.solid }}
                    aria-hidden="true"
                  />
                  <span aria-hidden="true">{st.glyph}</span>
                  {st.short}
                </span>
              )
            })}
          </div>
        </div>

        {/* Per-region trend */}
        <div className="border-t lg:border-t-0 lg:border-l hairline p-3">
          <div className="label mb-2">trend · last {hours}h</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-x-3 gap-y-1.5">
            {REGIONS.map((r) => {
              const rd = readings[r]
              const psi = rd?.psi_24h ?? null
              const st = bandStyle(psiBandKey(psi))
              const series = history?.regions[r] ?? []
              return (
                <div
                  key={r}
                  onMouseEnter={() => setHover(r)}
                  onMouseLeave={() => setHover(null)}
                  className={`flex items-center gap-2 rounded px-1.5 py-1 transition-colors ${
                    hover === r ? 'bg-subtle' : ''
                  }`}
                >
                  <span className="label !text-[9px] w-12 shrink-0">{r}</span>
                  <span
                    className="num text-[15px] font-semibold w-9 text-right shrink-0"
                    style={{ color: st.fg }}
                  >
                    {psi ?? '—'}
                  </span>
                  <Spark values={series} colour={st.solid} width={140} height={28} />
                </div>
              )
            })}
          </div>

          <p className="text-[10px] text-ink-mute leading-snug mt-2.5 max-w-[64ch]">
            Hourly 24-hour PSI from data.gov.sg
            {history?.source === 'fixture' && ' — replayed from a committed capture'}.
            An institution applies the reading for the region it is in; the
            island-wide figure understates the worst-affected region.
          </p>
        </div>
      </div>
    </div>
  )
}

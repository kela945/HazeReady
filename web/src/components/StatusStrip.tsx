import { bandStyle, relativeAge } from '../band'
import type { Conditions } from '../types'

/**
 * The persistent live status strip. The reading is the largest element on the
 * screen and its treatment changes with the band. Staleness is stated
 * explicitly rather than implied, and a fixture-backed reading says so.
 */
export default function StatusStrip({ c }: { c: Conditions | null }) {
  if (!c) {
    return (
      <div className="panel p-4 h-[132px] flex items-center">
        <span className="label">loading conditions…</span>
      </div>
    )
  }

  const b = bandStyle(c.band.band)
  const pm = bandStyle(c.pm25_band.band)
  const fLow = bandStyle(c.forecast.band_low)
  const fHigh = bandStyle(c.forecast.band_high)
  const isFixture = c.reading.source === 'fixture'

  return (
    <div
      className="panel overflow-hidden"
      style={{
        borderColor: b.weight === 'low' ? undefined : b.border,
        background: b.weight === 'critical' ? b.bg : undefined,
      }}
    >
      {b.weight === 'critical' && (
        <div
          className="px-4 py-1.5 text-[12px] font-medium tracking-wide"
          style={{ background: b.solid, color: '#ffffff' }}
        >
          {b.glyph} HAZARDOUS — persistent advisory in force. Avoid outdoor
          activity; vulnerable persons remain indoors.
        </div>
      )}

      <div className="p-4 grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-5 items-start">
        {/* Primary reading */}
        <div className="min-w-[200px]">
          <div className="label mb-1">24-hour PSI · {c.reading.region}</div>
          <div className="flex items-baseline gap-3">
            <span
              className="num text-[56px] leading-none font-semibold"
              style={{ color: b.fg }}
            >
              {c.reading.psi_24h ?? '—'}
            </span>
            <span
              className="text-[13px] font-medium px-2 py-1 rounded border"
              style={{ color: b.fg, background: b.bg, borderColor: b.border }}
            >
              <span aria-hidden="true">{b.glyph}</span> {b.label}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px] text-ink-mute">
            <span
              className={`inline-block w-1.5 h-1.5 rounded-full ${
                isFixture ? '' : 'live-dot'
              }`}
              style={{ background: isFixture ? '#78756c' : '#1f6f52' }}
            />
            <span className="num">
              updated {relativeAge(c.reading.staleness_seconds)}
            </span>
            {c.is_stale && (
              <span className="text-[#a8321f] font-medium">· STALE</span>
            )}
            {isFixture && (
              <span
                className="px-1.5 py-0.5 rounded border border-line"
                title={c.reading.note}
              >
                CACHED FIXTURE
              </span>
            )}
          </div>
        </div>

        {/* PM2.5 and forecast */}
        <div className="min-w-[220px] space-y-2.5">
          <div>
            <div className="label mb-0.5">1-hour PM2.5 · immediate decisions</div>
            <div className="flex items-baseline gap-2">
              <span className="num text-[24px] font-semibold" style={{ color: pm.fg }}>
                {c.reading.pm25_1h ?? '—'}
              </span>
              <span className="text-[11px] text-ink-mute">µg/m³</span>
              <span className="text-[11px]" style={{ color: pm.fg }}>
                <span aria-hidden="true">{pm.glyph}</span> {pm.label}
              </span>
            </div>
          </div>
          <div>
            <div className="label mb-0.5">24-hour outlook · plan against the worst band</div>
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="num text-[17px] font-semibold">
                {c.forecast.psi_low}–{c.forecast.psi_high}
              </span>
              <span className="text-[11px]" style={{ color: fLow.fg }}>
                {fLow.label}
              </span>
              {c.forecast.straddles_boundary && (
                <>
                  <span className="text-[11px] text-ink-mute">to</span>
                  <span className="text-[11px]" style={{ color: fHigh.fg }}>
                    {fHigh.label}
                  </span>
                </>
              )}
            </div>
            {c.forecast.source === 'derived' && (
              <div
                className="text-[10px] text-ink-mute mt-0.5 leading-snug"
                title={c.forecast.note}
              >
                DERIVED range, not an NEA forecast product
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

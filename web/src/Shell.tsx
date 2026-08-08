import { NavLink, Outlet } from 'react-router-dom'

const TABS = [
  { to: '/', label: 'Advisory', end: true },
  { to: '/monitor', label: 'Monitor', end: false },
  { to: '/report', label: 'Evaluation', end: false },
]

export default function Shell() {
  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b hairline bg-panel/80 backdrop-blur sticky top-0 z-30">
        <div className="max-w-[1400px] mx-auto px-4 h-12 flex items-center gap-6">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[13px] tracking-tight text-ink">
              HazeReady
            </span>
            <span className="label hidden sm:inline">
              operational haze advisory · singapore
            </span>
          </div>
          <nav className="ml-auto flex items-center gap-1">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  `px-3 py-1 text-[13px] rounded-md transition-colors ${
                    isActive
                      ? 'bg-active text-ink'
                      : 'text-ink-mute hover:text-ink'
                  }`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-[1400px] w-full mx-auto px-4 py-5">
        <Outlet />
      </main>

      {/* Non-dismissible. Rendered by the shell so no page can omit it. */}
      <footer className="border-t hairline bg-panel/90 sticky bottom-0 z-20">
        <div className="max-w-[1400px] mx-auto px-4 py-2 text-[11px] text-ink-mute leading-snug">
          Decision-support prototype. Official advisories at{' '}
          <a
            href="https://www.nea.gov.sg"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-ink"
          >
            nea.gov.sg
          </a>{' '}
          govern. Not medical or legal advice. No personal data is collected.
        </div>
      </footer>
    </div>
  )
}

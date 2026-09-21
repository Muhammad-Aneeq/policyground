import { useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { useHealth, usePolicies } from './api/client'
import type { Role } from './api/types'
import { RoleSwitcher } from './components/RoleSwitcher'
import { SyntheticDataBanner } from './components/aurora'
import { Admin } from './routes/Admin'
import { Chat } from './routes/Chat'
import { RolesDemo } from './routes/RolesDemo'
import { SourceViewer } from './routes/SourceViewer'

const NAV = [
  { to: '/', label: 'Chat', end: true },
  { to: '/sources', label: 'Sources', end: false },
  { to: '/admin', label: 'Admin', end: false },
  { to: '/roles', label: 'Roles demo', end: false },
]

/**
 * Shell: banner, role switcher, navigation.
 *
 * The session role lives here, above the router, so switching it on the Chat screen and then
 * navigating to Sources carries the same role. Holding it per screen would let the two surfaces
 * disagree about who is asking — which is exactly the inconsistency the roles demo exists to
 * disprove.
 */
export function App() {
  const [role, setRole] = useState<Role>('staff')
  const health = useHealth()
  const policies = usePolicies(role)

  return (
    <div className="min-h-full">
      <SyntheticDataBanner degraded={health.data?.degraded ?? false} />

      <header className="sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="grid h-8 w-8 place-items-center rounded-lg bg-accent font-display text-sm font-bold text-white"
            >
              §
            </span>
            <div>
              <div className="font-display text-lg font-semibold leading-none text-ink">
                PolicyGround
              </div>
              <div className="text-[11px] text-ink-soft">
                Governed finance RAG — cited, or it refuses
              </div>
            </div>
          </div>

          <nav className="flex gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-accent-wash text-accent-fg'
                      : 'text-ink-muted hover:bg-surface-sunken hover:text-ink'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto">
            <RoleSwitcher
              role={role}
              onChange={setRole}
              hiddenCount={policies.data?.hidden_count}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-5">
        <Routes>
          <Route path="/" element={<Chat role={role} />} />
          <Route path="/sources" element={<SourceViewer role={role} />} />
          <Route path="/sources/:policyId" element={<SourceViewer role={role} />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/roles" element={<RolesDemo />} />
        </Routes>
      </main>

      <footer className="mx-auto max-w-7xl px-4 pb-8 text-[11px] text-ink-soft">
        Built by an ex-accountant turned AI engineer. All policy content is synthetic.
        {health.data ? ` · APP_MODE=${health.data.app_mode}` : null}
      </footer>
    </div>
  )
}

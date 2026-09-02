import { ROLES, ROLE_DESCRIPTIONS, type Role } from '../api/types'

/**
 * The session-role toggle (spec 08 section 9, screen 4).
 *
 * The role is a **simulation** of an authenticated session — spec 08 section 11 says so, and this
 * control says so too rather than implying the switch is an access-control bypass. What is real is
 * everything downstream: the role travels to the retriever, the filter runs there, and restricted
 * passages never enter model context for an unprivileged role.
 */
export function RoleSwitcher({
  role,
  onChange,
  hiddenCount,
}: {
  role: Role
  onChange: (role: Role) => void
  hiddenCount?: number
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="role-switcher">
      <span className="text-xs uppercase tracking-wide text-slate-500">Session role</span>

      <div
        className="flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5"
        role="radiogroup"
        aria-label="Session role"
      >
        {ROLES.map((candidate) => (
          <button
            key={candidate}
            type="button"
            role="radio"
            aria-checked={role === candidate}
            onClick={() => onChange(candidate)}
            title={ROLE_DESCRIPTIONS[candidate]}
            data-testid={`role-${candidate}`}
            className={`rounded-md px-3 py-1 text-xs font-medium capitalize transition-colors ${
              role === candidate
                ? 'bg-emerald-brand/20 text-emerald-300'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {candidate}
          </button>
        ))}
      </div>

      {hiddenCount !== undefined && hiddenCount > 0 ? (
        <span className="text-xs text-amber-300/80" data-testid="hidden-count">
          {hiddenCount} polic{hiddenCount === 1 ? 'y' : 'ies'} hidden at this role
        </span>
      ) : null}
    </div>
  )
}

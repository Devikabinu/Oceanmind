import { NavLink, useLocation } from "react-router-dom";

export interface NavItem {
  to: string;
  label: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

const LINK = "flex items-center gap-2 rounded-md border-l-2 px-3 py-1.5 text-sm transition-colors";
const ACTIVE = "border-cyan-300 bg-white/10 font-semibold text-white";
const IDLE = "border-transparent text-sky-100/80 hover:bg-white/5 hover:text-white";

/** Vertical navigation: groups with a heading, single-link groups as a plain link. The active page is marked by a bar, a fill and aria-current. */
export default function NavMenu({ groups, onNavigate }: { groups: NavGroup[]; onNavigate?: () => void }) {
  const { pathname, search } = useLocation();
  return (
    <nav aria-label="Main" className="space-y-4">
      {groups.map((group) =>
        group.items.length === 1 ? (
          <NavLink
            key={group.label}
            to={group.items[0].to}
            end={group.items[0].to === "/"}
            onClick={onNavigate}
            className={({ isActive }) => `${LINK} ${isActive ? ACTIVE : IDLE}`}
          >
            {group.label}
          </NavLink>
        ) : (
          <div key={group.label}>
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/70">{group.label}</div>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const [base, query] = item.to.split("?");
                const active = query ? pathname === base && search === `?${query}` : pathname === base || pathname.startsWith(`${base}/`);
                // two links share /ecological-risk (with and without ?tab=species): only the exact one is active
                const shadowed = !query && group.items.some((o) => o.to.includes("?") && o.to.split("?")[0] === base && search === `?${o.to.split("?")[1]}`);
                const on = active && !shadowed;
                return (
                  <li key={item.to}>
                    <NavLink to={item.to} onClick={onNavigate} aria-current={on ? "page" : undefined} className={`${LINK} ${on ? ACTIVE : IDLE}`}>
                      {item.label}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ),
      )}
    </nav>
  );
}

import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { LogOut } from 'lucide-react';
import { navigationModules } from '../platform/moduleRegistry';

export default function Sidebar() {
  const { user, logout } = useAuth();
  const location = useLocation();

  return (
    <aside className="min-h-screen w-full flex flex-col bg-ink-950 border-r border-white/[0.06]">
      <div className="px-6 pt-8 pb-10">
        <div className="flex items-baseline gap-2">
          <h1 className="font-display text-3xl tracking-tight text-white" data-testid="brand-name">
            Lumina
          </h1>
          <span className="text-gold text-xs tracking-[0.3em] uppercase font-medium">AI</span>
        </div>
        <p className="mt-1 text-[11px] uppercase tracking-[0.25em] text-white/40">Desktop Studio</p>
      </div>

      <nav className="flex-1 px-3 space-y-1">
        {navigationModules().map(({ route, name, icon: Icon }) => {
          const active = location.pathname.startsWith(route);
          return (
            <NavLink
              key={route}
              to={route}
              data-testid={`nav-${route.split('/').pop()}`}
              className={`
                group flex items-center gap-3 px-4 py-3 rounded-md text-sm
                transition-colors duration-200
                ${active
                  ? 'bg-white/[0.04] text-white border-l-2 border-gold'
                  : 'text-white/60 hover:text-white hover:bg-white/[0.02] border-l-2 border-transparent'}
              `}
            >
              <Icon strokeWidth={1.25} className="w-4 h-4" />
              <span className="tracking-wide">{name}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-white/[0.06] px-4 py-4">
        <div className="flex items-center justify-between">
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-[0.2em] text-white/40">Owner</div>
            <div className="text-sm text-white/80 truncate" data-testid="owner-email">{user?.email}</div>
          </div>
          <button
            onClick={logout}
            data-testid="logout-btn"
            className="text-white/50 hover:text-gold transition-colors p-2"
            title="Logout"
          >
            <LogOut strokeWidth={1.25} className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

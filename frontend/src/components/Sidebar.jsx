import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ArrowLeft, Home, LogOut, MonitorPlay } from 'lucide-react';
import { navigationModules } from '../platform/moduleRegistry';

export default function Sidebar({ onClose, onOpenLivePreview }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const isDashboard = location.pathname === '/studio/dashboard' || location.pathname === '/studio';

  return (
    <aside className="min-h-screen w-full flex flex-col bg-ink-950 border-r border-white/[0.06]">
      <div className="border-b border-white/[0.06] px-6 pb-6 pt-6">
        <div className="flex items-baseline gap-2">
          <h1 className="font-display text-3xl tracking-tight text-white" data-testid="brand-name">
            Lumina
          </h1>
          <span className="text-gold text-xs tracking-[0.3em] uppercase font-medium">AI</span>
        </div>
        <p className="mt-1 text-xs font-medium uppercase tracking-[0.22em] text-white/45">Desktop Studio</p>
      </div>

      {/* ─── ΚΟΥΜΠΙ BACK ΓΙΑ ΕΠΙΣΤΡΟΦΗ ΣΤΗΝ ΑΡΧΙΚΗ (Αν είμαστε σε κάποιο AI Tool) ─── */}
      {!isDashboard && (
        <div className="px-4 pt-4 pb-1">
          <NavLink
            to="/studio/dashboard"
            onClick={onClose}
            data-testid="sidebar-back-button"
            className="flex items-center gap-2.5 rounded-lg border border-gold/50 bg-gold/15 px-3.5 py-3 text-sm font-bold text-gold hover:bg-gold hover:text-black transition shadow-lg"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>← Επιστροφή στην Αρχική</span>
          </NavLink>
        </div>
      )}

      {/* ─── ΖΩΝΤΑΝΗ ΠΡΟΕΠΙΣΚΟΠΗΣΗ ΕΦΑΡΜΟΓΗΣ (LIVE PREVIEW BUTTON) ─── */}
      <div className="px-4 pt-2 pb-2">
        <button
          type="button"
          onClick={() => {
            if (onClose) onClose();
            if (onOpenLivePreview) onOpenLivePreview();
          }}
          data-testid="sidebar-live-preview-button"
          className="flex w-full items-center justify-between rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3.5 py-2.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20 transition"
          title="Άνοιγμα της ζωντανής προεπισκόπησης της εφαρμογής"
        >
          <span className="flex items-center gap-2">
            <MonitorPlay className="h-4 w-4 text-emerald-400" />
            <span>Ζωντανή Προεπισκόπηση</span>
          </span>
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
        </button>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {navigationModules().map(({ route, name, icon: Icon }) => {
          const active = location.pathname.startsWith(route);
          return (
            <NavLink
              key={route}
              to={route}
              onClick={onClose}
              data-testid={`nav-${route.split('/').pop()}`}
              className={`
                group flex items-center gap-3 rounded-lg border-l-2 px-4 py-3 text-sm
                transition-colors duration-200
                ${active
                  ? 'border-gold bg-gold/[0.09] font-semibold text-white'
                  : 'border-transparent text-white/70 hover:bg-white/[0.045] hover:text-white'}
              `}
            >
              <Icon strokeWidth={1.6} className="h-[18px] w-[18px]" />
              <span className="tracking-wide">{name}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-white/[0.06] px-4 py-5">
        <div className="flex items-center justify-between">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-white/45">Owner</div>
            <div className="truncate text-sm text-white/85" data-testid="owner-email">{user?.email}</div>
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

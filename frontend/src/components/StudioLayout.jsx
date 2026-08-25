import { useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import Sidebar from './Sidebar';
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels';
import CommandPalette from './CommandPalette';
import { Home, Menu, PanelLeftClose, X } from 'lucide-react';
import { navigationModules } from '../platform/moduleRegistry';

const DASHBOARD_ROUTE = '/studio/dashboard';

export default function StudioLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const modules = useMemo(() => navigationModules(), []);
  const [sidebarOpen, setSidebarOpen] = useState(location.pathname === DASHBOARD_ROUTE);

  const currentModule = useMemo(
    () => modules.find(({ route }) => location.pathname.startsWith(route)),
    [location.pathname, modules],
  );

  useEffect(() => {
    setSidebarOpen(location.pathname === DASHBOARD_ROUTE);
  }, [location.pathname]);

  const goHome = () => {
    setSidebarOpen(true);
    navigate(DASHBOARD_ROUTE);
  };

  const switchTool = (event) => {
    const route = event.target.value;
    if (!route || route === location.pathname) return;
    setSidebarOpen(false);
    navigate(route);
  };

  const workspaceBar = (
    <div className="sticky top-0 z-30 flex min-h-14 items-center gap-2 border-b border-white/[0.06] bg-ink-950/95 px-2.5 py-2 backdrop-blur sm:px-4">
      <button
        type="button"
        onClick={() => setSidebarOpen((open) => !open)}
        data-testid="workspace-sidebar-toggle"
        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.03] text-white/70 transition-colors hover:border-gold/40 hover:text-gold"
        title={sidebarOpen ? 'Hide navigation' : 'Show navigation'}
        aria-label={sidebarOpen ? 'Hide navigation' : 'Show navigation'}
      >
        {sidebarOpen ? <PanelLeftClose className="h-4 w-4" strokeWidth={1.5} /> : <Menu className="h-4 w-4" strokeWidth={1.5} />}
      </button>

      <button
        type="button"
        onClick={goHome}
        data-testid="workspace-home"
        className="inline-flex h-9 shrink-0 items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 text-xs font-medium tracking-wide text-white/75 transition-colors hover:border-gold/40 hover:text-gold"
      >
        <Home className="h-4 w-4" strokeWidth={1.5} />
        <span className="hidden sm:inline">Home</span>
      </button>

      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-white/90">
          {currentModule?.name || 'LUMINA Studio'}
        </div>
        <div className="hidden truncate text-[10px] uppercase tracking-[0.2em] text-white/35 sm:block">
          Focus workspace
        </div>
      </div>

      <label className="sr-only" htmlFor="workspace-tool-switcher">Switch LUMINA tool</label>
      <select
        id="workspace-tool-switcher"
        value={currentModule?.route || ''}
        onChange={switchTool}
        data-testid="workspace-tool-switcher"
        className="h-9 max-w-[48vw] rounded-md border border-white/10 bg-ink-900 px-2 text-xs text-white/80 outline-none transition-colors focus:border-gold/50 sm:max-w-[260px] sm:px-3"
      >
        <option value="">Tools…</option>
        {modules.map(({ route, name }) => (
          <option key={route} value={route}>{name}</option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="min-h-screen w-full bg-ink-950 lumina-noise text-foreground">
      <div className="lg:hidden">
        {sidebarOpen && (
          <>
            <button
              type="button"
              aria-label="Close navigation overlay"
              onClick={() => setSidebarOpen(false)}
              className="fixed inset-0 z-40 bg-black/65"
            />
            <div className="fixed inset-y-0 left-0 z-50 w-[86vw] max-w-[320px] overflow-y-auto shadow-2xl">
              <button
                type="button"
                onClick={() => setSidebarOpen(false)}
                className="absolute right-3 top-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-md border border-white/10 bg-black/30 text-white/70"
                aria-label="Close navigation"
              >
                <X className="h-4 w-4" />
              </button>
              <Sidebar />
            </div>
          </>
        )}

        <main className="min-h-screen w-full overflow-visible">
          {workspaceBar}
          <Outlet />
          <CommandPalette />
        </main>
      </div>

      <div className="hidden lg:block">
        {sidebarOpen ? (
          <PanelGroup direction="horizontal" className="!h-auto min-h-screen w-full !overflow-visible">
            <Panel defaultSize={16} minSize={12} maxSize={22} className="min-h-screen !overflow-visible">
              <Sidebar />
            </Panel>
            <PanelResizeHandle className="w-px bg-white/[0.06] transition-colors hover:bg-gold/40" />
            <Panel minSize={40} className="min-h-screen !overflow-visible">
              <main className="min-h-screen w-full overflow-visible">
                {workspaceBar}
                <Outlet />
                <CommandPalette />
              </main>
            </Panel>
          </PanelGroup>
        ) : (
          <main className="min-h-screen w-full overflow-visible">
            {workspaceBar}
            <Outlet />
            <CommandPalette />
          </main>
        )}
      </div>
    </div>
  );
}
